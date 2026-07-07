# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    """Vertical de negocio del tenant.

    Determina qué homepage muestra el sitio público del tenant.
    Cada vertical instalable aporta su propio módulo
    `innatum_agenda_web_<vertical>` con su template estilizado.
    Si la opción seleccionada no tiene módulo instalado, el sitio
    cae al homepage genérico de `innatum_agenda_web`.
    """
    _inherit = 'res.company'

    vertical = fields.Selection(
        selection=[
            ('generic', 'Genérico'),
            ('odonto', 'Odontológico'),
        ],
        string='Vertical de negocio',
        default='generic',
        required=True,
        help='Vertical del tenant. Cambia el look del sitio público '
             '(/ y /citas) según el rubro: odontológico, peluquería, etc. '
             'El catálogo de servicios y agenda no se ven afectados.',
    )

    agenda_modo = fields.Selection(
        selection=[
            ('planificada', 'Planificada (slots pre-generados)'),
            ('directa', 'Directa (agenda on-demand)'),
        ],
        string='Modo de agenda',
        default='planificada',
        required=True,
        help='Cómo opera la agenda de este tenant (eje independiente del '
             'vertical):\n'
             '• Planificada: se crean planificaciones que pre-generan turnos '
             'de duración fija; reservar = elegir un turno disponible. '
             'Ideal para peluquería, lavadero, etc.\n'
             '• Directa: no hay planificación; la disponibilidad se calcula '
             'según el horario del profesional menos los turnos y bloqueos, '
             'y el turno se crea al agendar con la duración del servicio. '
             'Ideal para consultorios médicos/odontológicos con duración '
             'variable.\n'
             'Se puede cambiar en el tiempo: las citas ya agendadas se '
             'conservan; solo cambia cómo se calcula la disponibilidad futura.',
    )

    def write(self, vals):
        res = super().write(vals)
        # Si cambia el modo de agenda, re-sincroniza los grupos técnicos de
        # modo de los usuarios de esta(s) empresa(s) para actualizar la
        # visibilidad de los menús Planificación/Bloqueos en caliente.
        if 'agenda_modo' in vals:
            users = self.env['res.users'].sudo().search(
                [('company_id', 'in', self.ids)]
            )
            users._innatum_sync_agenda_modo_group()
        return res
