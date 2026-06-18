# -*- coding: utf-8 -*-
"""Prompts versionados.

El system prompt del agente WhatsApp NO es código — se compone en runtime a
partir de varias secciones almacenadas en BD:

  global_base       (reglas universales: JSON output, RDCM, formato)
  vertical          (tono por nicho, viene de innatum.vertical.template)
  business          (personalidad del tenant, viene de innatum.business.profile)
  capabilities      (qué tools tiene activadas el tenant)
  rdcm_rules        (defensas anti-alucinación)
  state_context     (qué puede hacer el agente en el estado actual de sesión)

Este modelo guarda las secciones reutilizables (global_base, rdcm_rules) con
versionado. Las dinámicas (vertical/business/capabilities/state) se componen
en el prompt_composer.
"""
from odoo import api, fields, models


class AiPrompt(models.Model):
    _name = 'innatum.ai.prompt'
    _description = 'AI Prompt Section'
    _order = 'code, version desc'

    code = fields.Char(
        string='Código',
        required=True,
        help='Identificador semántico de la sección. Ej: global_base, rdcm_rules.',
    )
    name = fields.Char(string='Nombre', required=True)
    version = fields.Integer(string='Versión', default=1, required=True)
    content = fields.Text(string='Contenido', required=True)
    description = fields.Text(string='Notas')
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('code_version_unique',
         'UNIQUE(code, version)',
         'El par (código, versión) debe ser único.'),
    ]

    @api.model
    def get_active(self, code):
        """Devuelve el contenido de la sección activa más reciente (version max)."""
        rec = self.search(
            [('code', '=', code), ('active', '=', True)],
            order='version desc',
            limit=1,
        )
        return rec.content if rec else ''
