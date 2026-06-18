# -*- coding: utf-8 -*-
"""RDCM (Retrieval-Driven Content Management) Layer 3.

Defensa contra alucinación heredada del patrón de Repuesto Experto. Tres capas:

  Layer 1: Chat memory reset cuando se inicia sesión nueva tras una terminal.
           → ya implementado en `innatum.ai.session.get_or_create`.

  Layer 2: System prompt explícito con reglas anti-alucinación.
           → vive en `innatum.ai.prompt` con code='rdcm_rules'.

  Layer 3: Post-procesamiento del JSON devuelto por el agente para descartar
           cosas inventadas (ej. servicios que no existen, slots fuera de horario).
           → este servicio.

En Fase 1B implementamos Layer 3 básico:
- Si el agente menciona un servicio en `extracted.servicio_nombre`, verificar
  que exista en `innatum.agenda.servicio` del tenant. Si no, descartar el campo
  y agregar nota al texto.
- Si menciona un horario en `extracted.fecha_hora`, verificar que sea fecha futura.
"""
import logging
from datetime import datetime
from odoo import api, models

_logger = logging.getLogger(__name__)


class Rdcm(models.AbstractModel):
    _name = 'innatum.rdcm'
    _description = 'RDCM Post-Processing Service'

    @api.model
    def post_process(self, response_dict, session):
        """Aplica Layer 3 a la respuesta del agente.

        Args:
          response_dict: dict con al menos {'text': str, 'extracted': dict?, ...}
          session: innatum.ai.session

        Returns:
          dict modificado (mismas keys, posiblemente con campos descartados)
        """
        if not isinstance(response_dict, dict):
            return response_dict

        extracted = response_dict.get('extracted') or {}
        if not isinstance(extracted, dict):
            return response_dict

        warnings = []
        company = session.company_id

        # Verificar servicio mencionado
        servicio_nombre = extracted.get('servicio_nombre')
        if servicio_nombre:
            exists = self.env['innatum.agenda.servicio'].sudo().search([
                ('name', 'ilike', servicio_nombre),
                ('company_id', 'in', [False, company.id]),
            ], limit=1)
            if not exists:
                warnings.append(f'servicio_nombre={servicio_nombre} no existe → descartado')
                extracted.pop('servicio_nombre', None)

        # Verificar fecha futura
        fecha_hora = extracted.get('fecha_hora')
        if fecha_hora:
            try:
                dt = fecha_hora if isinstance(fecha_hora, datetime) \
                    else datetime.fromisoformat(str(fecha_hora).replace('Z', '+00:00'))
                if dt < datetime.now():
                    warnings.append(f'fecha_hora={fecha_hora} es pasada → descartada')
                    extracted.pop('fecha_hora', None)
            except (ValueError, TypeError):
                warnings.append(f'fecha_hora={fecha_hora} formato inválido → descartado')
                extracted.pop('fecha_hora', None)

        # Verificar profesional mencionado
        profesional_id = extracted.get('profesional_id')
        if profesional_id:
            try:
                pid = int(profesional_id)
                exists = self.env['hr.employee'].sudo().search([
                    ('id', '=', pid),
                    ('company_id', 'in', [False, company.id]),
                ], limit=1)
                if not exists:
                    warnings.append(f'profesional_id={profesional_id} no existe → descartado')
                    extracted.pop('profesional_id', None)
            except (ValueError, TypeError):
                extracted.pop('profesional_id', None)

        response_dict['extracted'] = extracted
        if warnings:
            response_dict.setdefault('_rdcm_warnings', []).extend(warnings)
            _logger.info('RDCM Layer 3 warnings on session %s: %s',
                         session.id, '; '.join(warnings))
        return response_dict
