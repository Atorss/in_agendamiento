# -*- coding: utf-8 -*-
{
    'name': 'Innatum Agenda — IA',
    'version': '18.0.2.8.0',
    'category': 'Services',
    'summary': 'IA del SaaS de agendamiento: motor multi-proveedor, agente '
               'WhatsApp, chatbot web y tools de agendamiento',
    'description': """
        Módulo único de IA del SaaS de agendamiento Innatum. Fusiona en uno
        solo lo que antes eran cuatro módulos:

        - Motor IA multi-proveedor (Claude/OpenAI/Gemini): proveedores,
          herramientas, diccionario de datos, control de costos.
        - Agente WhatsApp (ex innatum_ai_core): sesiones, perfiles de negocio,
          plantillas de vertical, prompts versionados, webhook n8n.
        - Chatbot web (ex innatum_ai_web): widget del sitio público.
        - Tools de agendamiento (ex innatum_flow_scheduling): consultar/reservar
          turnos vía el agente.

        Incluye el gate de crédito IA por suscripción (antes en
        innatum_agenda_planes), que aquí no genera ciclo de dependencias.

        Copia exclusiva del SaaS de agendamiento. El motor genérico reutilizable
        vive aparte (in_nutricion/innatum_ai para nutrición); los paths los
        gestiona el despliegue.
    """,
    'author': 'Innatum',
    'website': 'https://www.innatum.com',
    'depends': [
        'base',
        'mail',
        'website',
        'muk_web_appsbar',
        'innatum_agenda_core',
        'innatum_agenda_admin',
        'innatum_agenda_planes',
    ],
    'data': [
        # Seguridad (grupos → ACL → reglas)
        'security/ai_security.xml',
        'security/ir.model.access.csv',
        'security/innatum_ai_core_rules.xml',
        'security/ai_web_rules.xml',
        # Data seed
        'data/ai_tools_data.xml',
        'data/vertical_template_data.xml',
        'data/ai_prompt_data.xml',
        'data/ai_tools_knowledge.xml',
        'data/ai_tools_scheduling.xml',
        'data/wa_outbound_cron.xml',
        # Vistas — motor
        'views/ai_conversation_views.xml',
        'views/ai_provider_views.xml',
        'views/ai_data_dict_views.xml',
        'views/ai_usage_log_views.xml',
        'views/res_config_settings_views.xml',
        # Vistas — agente
        'views/res_company_views.xml',
        'views/vertical_template_views.xml',
        'views/business_profile_views.xml',
        'views/business_knowledge_views.xml',
        'views/ai_session_views.xml',
        'views/ai_prompt_views.xml',
        'views/wizard_tenant_provisioning_views.xml',
        # Vistas — chatbot web
        'views/chatbot_templates.xml',
        # Menús (después de las acciones que referencian)
        'views/ai_menus.xml',
        'views/innatum_ai_core_menus.xml',
        'views/wa_outbound_views.xml',
        # Wiring de grupos de apps MuK (después de los menús)
        'data/menu_groups_innatum.xml',
        'data/menu_groups_wiring.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'innatum_agenda_ai/static/src/scss/whatsapp_inbox.scss',
            'innatum_agenda_ai/static/src/js/whatsapp_inbox.js',
            'innatum_agenda_ai/static/src/xml/whatsapp_inbox.xml',
        ],
        'web.assets_frontend': [
            'innatum_agenda_ai/static/src/scss/chatbot_widget.scss',
            'innatum_agenda_ai/static/src/js/chatbot_widget.js',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
