import { FastifyInstance } from 'fastify'
import { requireAuth } from '../middleware/auth'

export async function enrollmentRoutes(app: FastifyInstance) {
  const pipelineUrl = () => process.env.PIPELINE_URL || 'http://localhost:8000'

  // POST /enrollment/enroll
  // Forwards multipart form-data (provider_id, name, audio file) to the pipeline.
  // Fastify does not parse multipart/form-data by default — req.raw is the raw
  // Node.js stream so we can pass it straight through without a multipart plugin.
  app.post('/enrollment/enroll', { preHandler: requireAuth }, async (req, reply) => {
    const response = await fetch(`${pipelineUrl()}/enrollment/enroll`, {
      method: 'POST',
      headers: {
        'content-type':   req.headers['content-type']   ?? '',
        'content-length': req.headers['content-length'] ?? '',
      },
      body: req.raw,
      duplex: 'half',
    } as RequestInit)

    const status = response.status
    const json   = await response.json()
    return reply.status(status).send(json)
  })

  // GET /enrollment/providers — list all enrolled providers (no raw embeddings)
  app.get('/enrollment/providers', { preHandler: requireAuth }, async (_req, reply) => {
    const response = await fetch(`${pipelineUrl()}/enrollment/providers`)

    if (!response.ok) {
      return reply.status(response.status).send({ error: 'Failed to fetch providers' })
    }

    return reply.send(await response.json())
  })

  // DELETE /enrollment/:providerId — remove a provider voice profile
  app.delete('/enrollment/:providerId', { preHandler: requireAuth }, async (req, reply) => {
    const { providerId } = req.params as { providerId: string }

    const response = await fetch(`${pipelineUrl()}/enrollment/${providerId}`, {
      method: 'DELETE',
    })

    const status = response.status
    const json   = await response.json()
    return reply.status(status).send(json)
  })
}
