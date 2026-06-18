# -*- coding: utf-8 -*-
{
    'name': 'Innatum AI Core',
    'version': '18.0.0.3.0',
    'category': 'Services',
    'summary': 'Base multi-tenant para agente WhatsApp (Business Profile, Sesiones, Templates, Prompts, RDCM)',
    'description': """
Base común para el agente WhatsApp SaaS multi-vertical.
Provee:
- Business Profile por tenant (vertical, capacidades, tono)
- Vertical Template (odontología, spa, florería, etc.)
- AI Session con máquina de estados
- Endpoint /api/whatsapp/message (orquesta agente IA)
- Prompts versionados + Prompt Composer
- WhatsApp Agent: motor que llama a engine + tools
- RDCM Layer 3 (post-process anti-alucinación)
- Extensión innatum.ai.tool (tool_type='wa_agent' con custom_input_schema)
- Extensión res.company con wa_phone_number_id y wa_agent_user
""",
    'author': 'Innatum',
    'website': 'https://www.innatum.com',
    'depends': [
        'base',
        'mail',
        'innatum_ai',
        'innatum_agenda_core',
        'innatum_agenda_admin',
        'innatum_agenda_planes',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/innatum_ai_core_rules.xml',
        'data/vertical_template_data.xml',
        'data/ai_prompt_data.xml',
        'views/res_company_views.xml',
        'views/vertical_template_views.xml',
        'views/business_profile_views.xml',
        'views/ai_session_views.xml',
        'views/ai_prompt_views.xml',
        'views/innatum_ai_core_menus.xml',
        'views/wizard_tenant_provisioning_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
