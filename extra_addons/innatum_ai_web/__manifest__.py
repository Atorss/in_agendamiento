# -*- coding: utf-8 -*-
{
    'name': 'Innatum AI - Chatbot Agendamiento Web',
    'version': '18.0.1.3.0',
    'category': 'Services',
    'summary': 'Chatbot con IA para agendar citas desde el sitio web',
    'description': """
        Agrega un chatbot flotante al sitio web público que permite a los clientes
        agendar citas usando lenguaje natural. Integrado con el motor de IA
        multi-proveedor (Claude, OpenAI, Gemini).

        Seguridad: solo accede a turnos disponibles y datos mínimos del cliente.
        No expone el ORM genérico.
    """,
    'author': 'Innatum',
    'website': 'https://www.innatum.com',
    'depends': ['innatum_ai', 'innatum_agenda_core', 'website'],
    'data': [
        'security/ir.model.access.csv',
        'security/ai_web_rules.xml',
        'views/chatbot_templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'innatum_ai_web/static/src/scss/chatbot_widget.scss',
            'innatum_ai_web/static/src/js/chatbot_widget.js',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
