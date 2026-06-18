# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class VerticalTemplate(models.Model):
    """Plantilla pre-configurada de un vertical de negocio.

    Define el lenguaje/tono típico, capacidades por defecto y estructura de
    datos esperada para un nicho (odontología, spa, etc.). El business profile
    de cada tenant deriva de una template y la personaliza.
    """
    _name = 'innatum.vertical.template'
    _description = 'Vertical Template'
    _order = 'family, name'

    code = fields.Char(
        string='Código',
        required=True,
        help='Identificador único del vertical (snake_case). Ej: odontologia, spa.',
    )
    name = fields.Char(string='Nombre', required=True, translate=True)
    family = fields.Selection(
        [('A', 'Agendamiento'), ('B', 'Productos + Envío'), ('HYBRID', 'Híbrido')],
        string='Familia',
        required=True,
    )
    description = fields.Text(string='Descripción')
    base_personality_prompt = fields.Text(
        string='Prompt de personalidad base',
        help='Tono y reglas comunes del nicho. Se compone con el personality del tenant.',
    )
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('code_unique', 'UNIQUE(code)', 'El código del vertical debe ser único.'),
    ]

    @api.constrains('family')
    def _check_family(self):
        for rec in self:
            if rec.family not in ('A', 'B', 'HYBRID'):
                raise ValidationError(
                    'La familia debe ser A, B o HYBRID. Recibido: %s' % rec.family
                )
