# -*- coding: utf-8 -*-
"""Activa la autoplanificación para los colaboradores existentes.

El default de `puede_planificar` cambió de False a True ("cada profesional
administra su propia agenda"). Esta migración alinea los empleados ya creados
(que tenían False) con el nuevo default. El admin puede revocarlo puntualmente
desde el form del colaborador.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute(
        "UPDATE hr_employee SET puede_planificar = TRUE "
        "WHERE puede_planificar IS DISTINCT FROM TRUE"
    )
    _logger.info(
        'innatum_agenda_admin: puede_planificar=True aplicado a %d colaborador(es) '
        'existentes (nuevo default).', cr.rowcount,
    )
