# -*- coding: utf-8 -*-
"""Pre-migration 18.0.4.0.0 — convierte servicio.company_id (M2O) a
company_ids (M2M).

Se ejecuta ANTES de cargar el nuevo XML del módulo: copia los valores
de company_id existentes a la tabla relacional nueva, luego deja que
Odoo elimine la columna company_id como parte del upgrade.

Cualquier servicio que tuviera company_id seteado queda asignado al
nuevo M2M con esa misma company. Servicios con company_id NULL (raro
en producción) quedan sin asignación — Innatum los puede asignar
después desde el menú catálogo.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # 1. Crear la tabla relacional M2M si no existe
    cr.execute("""
        CREATE TABLE IF NOT EXISTS innatum_agenda_servicio_company_rel (
            servicio_id INTEGER NOT NULL REFERENCES innatum_agenda_servicio(id)
                ON DELETE CASCADE,
            company_id INTEGER NOT NULL REFERENCES res_company(id)
                ON DELETE CASCADE,
            PRIMARY KEY (servicio_id, company_id)
        )
    """)

    # 2. Copiar company_id existente a la M2M (preserva la asignación actual)
    cr.execute("""
        INSERT INTO innatum_agenda_servicio_company_rel (servicio_id, company_id)
        SELECT id, company_id
        FROM innatum_agenda_servicio
        WHERE company_id IS NOT NULL
        ON CONFLICT DO NOTHING
    """)
    _logger.info(
        'Migration servicio: %s asignaciones M2M creadas desde company_id',
        cr.rowcount,
    )

    # 3. Eliminar la columna company_id vieja (Odoo no la quita
    # automáticamente porque el modelo Python ya no la declara)
    cr.execute("""
        ALTER TABLE innatum_agenda_servicio DROP COLUMN IF EXISTS company_id
    """)
