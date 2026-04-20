import { FastifyInstance } from 'fastify'
import { requireAuth } from '../middleware/auth'

const SOAP_SECTIONS = ['S', 'O', 'A', 'P', 'UNCLASSIFIED']
const VISIT_TYPES   = ['new_patient', 'follow_up', 'urgent_care', 'telehealth']

// Guardrail: prevents double-approval from rapid re-clicks or duplicate requests
const approvalsInFlight = new Set<string>()

export async function noteRoutes(app: FastifyInstance) {
  // GET /session/:id/note — fetch structured review payload after pipeline runs
  app.get('/session/:id/note', { preHandler: requireAuth }, async (req, reply) => {
    const { id: sessionId } = req.params as { id: string }

    const pipelineUrl = process.env.PIPELINE_URL || 'http://localhost:8000'
    const response = await fetch(`${pipelineUrl}/session/${sessionId}/note`)

    if (!response.ok) {
      return reply.status(404).send({ error: 'Note not found' })
    }

    return reply.send(await response.json())
  })

  // POST /session/:id/approve — provider approves note, triggers FHIR generation
  app.post('/session/:id/approve', {
    preHandler: requireAuth,
    schema: {
      body: {
        type: 'object',
        required: ['provider_npi', 'patient_mrn', 'visit_type'],
        properties: {
          provider_npi: { type: 'string', minLength: 1 },
          patient_mrn:  { type: 'string', minLength: 1 },
          visit_type:   { type: 'string', enum: VISIT_TYPES }
        },
        additionalProperties: false
      }
    }
  }, async (req, reply) => {
    const { id: sessionId } = req.params as { id: string }

    // Guardrail: reject duplicate approval requests for the same session
    if (approvalsInFlight.has(sessionId)) {
      return reply.status(409).send({ error: 'Approval already in progress for this session' })
    }

    const body = req.body as {
      provider_npi: string
      patient_mrn: string
      visit_type: string
    }

    approvalsInFlight.add(sessionId)
    try {
      const pipelineUrl = process.env.PIPELINE_URL || 'http://localhost:8000'
      const response = await fetch(`${pipelineUrl}/session/${sessionId}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      })
      return reply.send(await response.json())
    } finally {
      approvalsInFlight.delete(sessionId)
    }
  })

  // POST /session/:id/segment/:segId/remap — provider drags segment to different SOAP section
  app.post('/session/:id/segment/:segId/remap', {
    preHandler: requireAuth,
    schema: {
      body: {
        type: 'object',
        required: ['from_section', 'to_section', 'provider_id'],
        properties: {
          from_section: { type: 'string', enum: SOAP_SECTIONS },
          to_section:   { type: 'string', enum: SOAP_SECTIONS },
          provider_id:  { type: 'string', minLength: 1 }
        },
        additionalProperties: false
      }
    }
  }, async (req, reply) => {
    const { id: sessionId, segId } = req.params as { id: string; segId: string }
    const { from_section, to_section, provider_id } = req.body as {
      from_section: string
      to_section: string
      provider_id: string
    }

    const pipelineUrl = process.env.PIPELINE_URL || 'http://localhost:8000'
    const response = await fetch(`${pipelineUrl}/segment/${segId}/remap`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId, from_section, to_section, provider_id })
    })

    return reply.send(await response.json())
  })

  // POST /session/:id/segment/:segId/edit — provider corrects transcription text
  app.post('/session/:id/segment/:segId/edit', {
    preHandler: requireAuth,
    schema: {
      body: {
        type: 'object',
        required: ['corrected_text', 'provider_id'],
        properties: {
          corrected_text: { type: 'string', minLength: 1 },
          provider_id:    { type: 'string', minLength: 1 }
        },
        additionalProperties: false
      }
    }
  }, async (req, reply) => {
    const { id: sessionId, segId } = req.params as { id: string; segId: string }
    const { corrected_text, provider_id } = req.body as {
      corrected_text: string
      provider_id: string
    }

    const pipelineUrl = process.env.PIPELINE_URL || 'http://localhost:8000'
    const response = await fetch(`${pipelineUrl}/segment/${segId}/edit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId, corrected_text, provider_id })
    })

    return reply.send(await response.json())
  })

  // DELETE /session/:id/segment/:segId — provider removes a segment
  app.delete('/session/:id/segment/:segId', {
    preHandler: requireAuth,
    schema: {
      body: {
        type: 'object',
        required: ['provider_id'],
        properties: {
          provider_id: { type: 'string', minLength: 1 },
          reason:      { type: 'string' }
        },
        additionalProperties: false
      }
    }
  }, async (req, reply) => {
    const { id: sessionId, segId } = req.params as { id: string; segId: string }
    const { provider_id, reason } = req.body as { provider_id: string; reason?: string }

    const pipelineUrl = process.env.PIPELINE_URL || 'http://localhost:8000'
    const response = await fetch(`${pipelineUrl}/segment/${segId}`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId, provider_id, reason })
    })

    return reply.send(await response.json())
  })

  // POST /session/:id/amendment — provider adds new clinical info not in transcript
  app.post('/session/:id/amendment', {
    preHandler: requireAuth,
    schema: {
      body: {
        type: 'object',
        required: ['content', 'soap_section', 'provider_id'],
        properties: {
          content:      { type: 'string', minLength: 1 },
          soap_section: { type: 'string', enum: ['S', 'O', 'A', 'P'] },
          provider_id:  { type: 'string', minLength: 1 }
        },
        additionalProperties: false
      }
    }
  }, async (req, reply) => {
    const { id: sessionId } = req.params as { id: string }
    const { content, soap_section, provider_id } = req.body as {
      content: string
      soap_section: string
      provider_id: string
    }

    const pipelineUrl = process.env.PIPELINE_URL || 'http://localhost:8000'
    const response = await fetch(`${pipelineUrl}/session/${sessionId}/amendment`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content, soap_section, provider_id })
    })

    return reply.send(await response.json())
  })
}
