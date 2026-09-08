"""FHIR emission layer for HiScribe.

Turns an approved session into a FHIR R4B transaction Bundle and hands it to a
sink. Import from `client` rather than from a concrete sink so the destination
can be swapped by changing one line, matching the adapter convention used
throughout `pipeline/adapters/`.
"""
