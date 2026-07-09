# -*- coding: utf-8 -*-
"""Notificación WhatsApp al colaborador cuando se crea una derivación.

Vive en el módulo AI (no en core) para que innatum_agenda_core quede
limpio de lógica de WhatsApp. Se engancha en create() — no en el wizard —
para que cualquier vía que cree derivaciones (wizard hoy, asistente IA en
fases futuras) notifique automáticamente.
"""
import logging

from odoo import _, api, models

_logger = logging.getLogger(__name__)


class InnatumAgendaTurnoWa(models.Model):
    _inherit = 'innatum.agenda.turno'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if rec.es_derivacion and rec.state == 'derivado':
                try:
                    rec._notificar_derivacion_whatsapp()
                except Exception:  # la notificación jamás rompe la derivación
                    _logger.exception(
                        'No se pudo encolar la notificación WhatsApp de la '
                        'derivación %s', rec.id)
        return records

    def _wa_notificar_o_chatter(self, raw, template_name, variables,
                                category, degrade_msg, buttons=None):
        """Encola la plantilla si el número es válido; si no, deja el aviso
        en el chatter. Devuelve True si se encoló."""
        self.ensure_one()
        Outbound = self.env['innatum.wa.outbound']
        if not Outbound.normalize_ec_number(raw):
            self.message_post(body=degrade_msg)
            return False
        Outbound.queue_template(
            self.company_id, raw, template_name, variables,
            origin=self, category=category, buttons=buttons)
        return True

    def _notificar_derivacion_whatsapp(self):
        """Encola la plantilla `derivacion_colaborador` para quien atiende.

        Variables de la plantilla (orden fijo, contrato con Meta):
        1=colaborador, 2=quien deriva, 3=paciente, 4=servicio.
        El botón quick-reply de la plantilla devuelve st_deriv:<id>: el tap
        abre esta derivación directo en el chat del colaborador.
        Sin móvil válido: la derivación sigue su flujo normal y queda nota
        en su chatter (el respaldo es el menú Derivaciones del sistema).
        """
        self.ensure_one()
        colaborador = self.professional_id
        raw = colaborador.mobile_phone or colaborador.work_phone
        self._wa_notificar_o_chatter(
            raw, 'derivacion_colaborador',
            [
                colaborador.name or '-',
                self.derivado_por_id.name or '-',
                self.partner_id.name or '-',
                self.servicio_id.name or '-',
            ],
            buttons=['st_deriv:%d' % self.id],
            category='derivacion_colaborador',
            degrade_msg=_(
                'No se pudo notificar por WhatsApp a %s: sin número de '
                'celular válido en su ficha de empleado.'
            ) % (colaborador.name or '-'),
        )

    # ------------------------------------------------------------------
    # Fase 2: ciclo de la derivación por WhatsApp
    # ------------------------------------------------------------------

    def action_confirmar_derivacion(self):
        """Al confirmar las propuestas (por WhatsApp o backend), avisar al
        paciente con la plantilla `derivacion_paciente`."""
        res = super().action_confirmar_derivacion()
        for rec in self:
            try:
                rec._notificar_paciente_derivacion_propuesta()
            except Exception:  # la notificación jamás rompe la confirmación
                _logger.exception(
                    'No se pudo encolar el aviso al paciente de la '
                    'derivación %s', rec.id)
        return res

    def _notificar_paciente_derivacion_propuesta(self):
        """Plantilla `derivacion_paciente` (1=paciente, 2=quien deriva,
        3=colaborador, 4=servicio). Botones quick-reply: 'Ver horarios'
        (dp_deriv:<id>, muestra las propuestas de ESTA derivación) y
        'Ahora no' (dp_menu:back)."""
        self.ensure_one()
        partner = self.partner_id
        raw = (partner.mobile or partner.phone) if partner else False
        self._wa_notificar_o_chatter(
            raw, 'derivacion_paciente',
            [
                partner.name or '-',
                self.derivado_por_id.name or '-',
                self.professional_id.name or '-',
                self.servicio_id.name or '-',
            ],
            buttons=['dp_deriv:%d' % self.id, 'dp_menu:back'],
            category='derivacion_paciente',
            degrade_msg=_(
                'No se pudo avisar al paciente por WhatsApp: sin número '
                'de celular válido.'),
        )

    def _queue_aviso_agenda(self, emp, detalle):
        """Encola la plantilla comodín `aviso_agenda` (1=destinatario,
        2=detalle) a un empleado; degrada con nota en chatter."""
        self.ensure_one()
        raw = (emp.mobile_phone or emp.work_phone) if emp else False
        self._wa_notificar_o_chatter(
            raw, 'aviso_agenda',
            [emp.name or '-', detalle],
            category='aviso_agenda',
            degrade_msg=_(
                'No se pudo notificar por WhatsApp a %s: sin número '
                'de celular válido.') % (emp.name if emp else '-'),
        )

    def _notificar_repropuesta_necesaria(self):
        """El horario elegido se ocupó y no quedan propuestas: avisar al
        colaborador para que proponga de nuevo (plantilla aviso_agenda)."""
        self.ensure_one()
        self._queue_aviso_agenda(
            self.professional_id,
            'el horario que eligió %s ya se ocupó; propone nuevos '
            'horarios para su derivación' % (self.partner_id.name
                                             or 'el paciente'))

    def _notificar_derivacion_agendada(self):
        """El horario quedó elegido (paciente por WhatsApp o backend):
        confirmar al colaborador y a quien derivó con `aviso_agenda`."""
        self.ensure_one()
        Agent = self.env['innatum.whatsapp.agent']
        cuando = (Agent._fmt_dt_ec(self.date_start)
                  if self.date_start else '-')
        detalle = 'se agendó tu derivación: %s, %s' % (
            self.partner_id.name or '-', cuando)
        destinatarios = self.professional_id
        if self.derivado_por_id and self.derivado_por_id != self.professional_id:
            destinatarios |= self.derivado_por_id
        for emp in destinatarios:
            self._queue_aviso_agenda(emp, detalle)


class InnatumAgendaTurnoPropuestaWa(models.Model):
    """Al elegirse una propuesta (por el paciente vía WhatsApp o desde el
    backend), se confirman las tres partes."""
    _inherit = 'innatum.agenda.turno.propuesta'

    def action_elegir(self):
        deriv = self.derivacion_id
        res = super().action_elegir()
        try:
            deriv._notificar_derivacion_agendada()
        except Exception:  # la notificación jamás rompe la elección
            _logger.exception(
                'No se pudo encolar la confirmación de la derivación %s',
                deriv.id)
        return res
