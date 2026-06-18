# -*- coding: utf-8 -*-

import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Sincroniza el grupo técnico 'Puede facturar' para empleados que ya
    tenían el flag activo antes de la introducción del grupo."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    employees = env['hr.employee'].search([('user_id', '!=', False)])
    if not employees:
        return
    employees._innatum_facturacion_sync_groups()
    _logger.info(
        'innatum_agenda_facturacion: sincronizado grupo "Puede facturar" '
        'sobre %d empleados con usuario.',
        len(employees),
    )
