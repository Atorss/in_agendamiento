# -*- coding: utf-8 -*-
"""Backfill servicio_ids (M2M) desde servicio_id (M2O) anterior.

Antes de 18.0.2.0.0:
  - innatum.agenda.config tenía servicio_id (M2O, opcional)
  - innatum.agenda.turno tenía servicio_id (M2O, required)

Desde 18.0.2.0.0:
  - innatum.agenda.config tiene servicio_ids (M2M)
  - innatum.agenda.turno tiene servicio_id (M2O opcional, el "elegido")
    + servicio_ids (M2M, las "opciones")
"""


def migrate(cr, version):
    if not version:
        return  # primera instalación

    # 1) Config: copiar servicio_id (si la columna aún existe) → servicio_ids
    cr.execute("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name='innatum_agenda_config' AND column_name='servicio_id'
        )
    """)
    config_has_servicio_id = cr.fetchone()[0]
    if config_has_servicio_id:
        cr.execute("""
            INSERT INTO innatum_agenda_config_servicio_rel (config_id, servicio_id)
            SELECT id, servicio_id
            FROM innatum_agenda_config
            WHERE servicio_id IS NOT NULL
            ON CONFLICT DO NOTHING
        """)

    # 2) Turno: backfill servicio_ids con el servicio_id existente
    cr.execute("""
        INSERT INTO innatum_agenda_turno_servicio_rel (turno_id, servicio_id)
        SELECT id, servicio_id
        FROM innatum_agenda_turno
        WHERE servicio_id IS NOT NULL
        ON CONFLICT DO NOTHING
    """)
