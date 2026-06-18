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
