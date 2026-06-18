# -*- coding: utf-8 -*-
{
    'name': 'Innatum AI Engine',
    'version': '18.0.1.5.0',
    'category': 'Services',
    'summary': 'Motor de IA multi-proveedor para Odoo (Claude, OpenAI, Gemini)',
    'description': """
        Motor genérico de inteligencia artificial para Odoo 18.
        Provee conexión multi-proveedor: Claude (Anthropic), OpenAI, Google Gemini.
        Otros módulos pueden depender de este para hacer llamadas a APIs de IA.
    """,
    'author': 'Innatum',
    'website': 'https://www.innatum.com',
    'depends': ['base', 'mail', 'muk_web_appsbar'],
    'data': [
        'security/ai_security.xml',
        'security/ir.model.access.csv',
        'data/ai_tools_data.xml',
        'views/ai_conversation_views.xml',
        'views/ai_provider_views.xml',
        'views/ai_data_dict_views.xml',
        'views/ai_usage_log_views.xml',
        'views/res_config_settings_views.xml',
        'views/ai_menus.xml',
        'data/menu_groups_innatum.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
