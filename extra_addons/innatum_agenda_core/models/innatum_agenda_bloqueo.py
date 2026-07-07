# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError


class InnatumAgendaBloqueo(models.Model):
    """Bloqueo de agenda (modo de agenda 'directa').

    Espacio de tiempo en el que un profesional NO puede recibir turnos
    (ej. una reunión de 2 a 5pm). Se muestra en el mismo calendario que los
    turnos y el cálculo de disponibilidad on-demand lo resta. NO es una
    ausencia de RRHH: es un evento propio de la agenda.
    """
    _name = 'innatum.agenda.bloqueo'
    _description = 'Bloqueo de agenda'
    _order = 'date_start desc'

    name = fields.Char(
        string='Título', compute='_compute_name', store=True,
    )
    professional_id = fields.Many2one(
        'hr.employee', string='Profesional', required=True,
        ondelete='cascade',
        default=lambda self: self._default_professional_id(),
    )

    @api.model
    def _default_professional_id(self):
        """Cada colaborador crea sus PROPIOS bloqueos: por defecto se
        precarga su propio empleado. El aislamiento real (no crear/editar
        bloqueos de otros) lo garantiza la record rule rule_bloqueo_own."""
        return self.env.user.employee_id
    company_id = fields.Many2one(
        'res.company', string='Empresa',
        related='professional_id.company_id', store=True, readonly=True,
    )
    date_start = fields.Datetime(string='Inicio', required=True)
    date_end = fields.Datetime(string='Fin', required=True)
    motivo = fields.Char(string='Motivo')
    color = fields.Integer(
        string='Color', default=9,
        help='Color con el que se muestra el bloqueo en los calendarios. '
             'Por defecto un tono neutro para distinguirlo de los turnos.',
    )

    @api.depends('professional_id', 'date_start', 'motivo')
    def _compute_name(self):
        for rec in self:
            label = rec.motivo or 'Bloqueo'
            if rec.professional_id:
                label = '%s · %s' % (rec.professional_id.name, label)
            rec.name = label

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for rec in self:
            if rec.date_start and rec.date_end and rec.date_end <= rec.date_start:
                raise ValidationError(
                    'El fin del bloqueo debe ser posterior al inicio.')

    @api.constrains('date_start', 'date_end')
    def _check_not_past(self):
        """No tiene sentido bloquear tiempo ya transcurrido: la disponibilidad
        solo mira hacia adelante. Se rechaza un bloqueo cuyo fin ya pasó.
        Mismo patrón (y bypass) que el turno para migraciones/importaciones."""
        for rec in self:
            if rec.date_end and rec.date_end < fields.Datetime.now():
                if self.env.context.get('allow_past_dates'):
                    continue
                raise ValidationError(
                    'No se puede crear un bloqueo en una fecha ya pasada.')

    @api.constrains('date_start', 'date_end', 'professional_id')
    def _check_no_overlap_turno(self):
        """No permitir bloquear un horario en el que el profesional ya tiene un
        turno (no cancelado): sería contradictorio (bloqueado y con cita a la
        vez). Simétrico al chequeo del lado del turno. Sudo porque los turnos
        pueden no ser visibles para el dueño del bloqueo."""
        Turno = self.env['innatum.agenda.turno'].sudo()
        for rec in self:
            if not rec.date_start or not rec.date_end or not rec.professional_id:
                continue
            turno = Turno.search([
                ('professional_id', '=', rec.professional_id.id),
                ('state', '!=', 'cancelled'),
                ('date_start', '<', rec.date_end),
                ('date_end', '>', rec.date_start),
            ], limit=1)
            if turno:
                raise ValidationError(
                    'No se puede crear el bloqueo: el profesional ya tiene un '
                    'turno en ese horario.\n\nTurno: %s (%s - %s)' % (
                        turno.name,
                        turno.date_start.strftime('%d/%m/%Y %H:%M'),
                        turno.date_end.strftime('%H:%M'),
                    )
                )
