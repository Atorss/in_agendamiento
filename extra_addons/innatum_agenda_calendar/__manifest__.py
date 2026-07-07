# -*- coding: utf-8 -*-
{
    'name': 'Innatum Agenda — Calendario Interactivo',
    'version': '18.0.1.0.0',
    'category': 'Services',
    'summary': 'Calendario interactivo (OWL) para los turnos del SaaS de '
               'agendamiento: vistas mes/semana/día, drag & drop, modal de día.',
    'description': """
Calendario Interactivo de Turnos
================================

Módulo **aislado** que añade una vista de calendario rica, construida con OWL,
inspirada en CalendarKit (calendarkit.io) y la estética de UntitledUI.

Características
--------------
- Vistas **Mes / Semana / Día** con navegación (Hoy / ‹ / ›).
- **Drag & drop** para reagendar turnos (respeta los constraints del core,
  incluido el solape por profesional).
- **Click en un hueco** para crear un turno nuevo (abre el form view del core
  en un diálogo, así se respetan onchanges, constraints y el modo dual).
- **Modal de día**: al hacer click en un día se abre una agenda en grande.
- **Filtros** por profesional, servicio y estado, con colores por estado.

Aislamiento
-----------
Este módulo **no añade ni hereda modelos Python**: solo registra una
``ir.actions.client`` OWL, un menú y los assets. Toda la lectura/escritura se
hace contra ``innatum.agenda.turno`` vía el servicio ORM del web client, por lo
que no interfiere con el resto de módulos de ``in_agendamiento``.
    """,
    'author': 'Innatum',
    'website': 'https://www.innatum.com',
    'depends': [
        'web',
        'innatum_agenda_core',
    ],
    'data': [
        'views/calendar_action.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'innatum_agenda_calendar/static/src/scss/calendar_view.scss',
            'innatum_agenda_calendar/static/src/js/calendar_view.js',
            'innatum_agenda_calendar/static/src/xml/calendar_view.xml',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
