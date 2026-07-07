# -*- coding: utf-8 -*-
"""Renombra la columna turno_id -> derivacion_id en la tabla de propuestas.

El campo que vincula cada propuesta con el turno principal de la derivación
pasó de llamarse `turno_id` a `derivacion_id` (relación explícita y sólida).
Se renombra la columna ANTES de que el ORM cargue el nuevo campo requerido,
para preservar el vínculo de las propuestas existentes y evitar violar la
restricción NOT NULL.
"""


def migrate(cr, version):
    cr.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'innatum_agenda_turno_propuesta'
          AND column_name IN ('turno_id', 'derivacion_id')
    """)
    cols = {row[0] for row in cr.fetchall()}
    if 'turno_id' in cols and 'derivacion_id' not in cols:
        cr.execute(
            "ALTER TABLE innatum_agenda_turno_propuesta "
            "RENAME COLUMN turno_id TO derivacion_id"
        )
