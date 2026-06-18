# -*- coding: utf-8 -*-
{
    'name': 'Innatum Flow Scheduling (Familia A)',
    'version': '18.0.0.1.0',
    'category': 'Services',
    'summary': 'Tools del agente WhatsApp para agendamiento (consultar servicios/profesionales/horarios, reservar)',
    'description': """
Tools de Familia A (Agendamiento) para el agente WhatsApp.

Provee 6 tools registradas como innatum.ai.tool con tool_type='wa_agent':
- consultar_servicios
- consultar_profesionales
- buscar_horarios_disponibles
- identificar_cliente
- reservar_turno
- solicitar_handoff (básico Fase 1B)

Los métodos Python que ejecutan estas tools viven en `flow.scheduling.tools`.
""",
    'author': 'Innatum',
    'website': 'https://www.innatum.com',
    'depends': ['innatum_ai_core', 'innatum_agenda_core'],
    'data': [
        'data/ai_tools_scheduling.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
