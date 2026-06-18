# -*- coding: utf-8 -*-
{
    'name': 'Innatum SaaS — Suma IA',
    'summary': 'Agrega chatbot IA con gate por suscripción y consumo controlado por recargas',
    'description': """
        Módulo meta (sin código propio) que suma capacidades de IA al
        SaaS de agendamiento. Requiere innatum_basico instalado primero
        (se instala automáticamente como dependencia).

        Agrega:
        - innatum_ai: motor IA multi-proveedor (Claude, OpenAI, Gemini),
          providers y log de uso multi-tenant.
        - innatum_ai_web: chatbot público en cada subdominio del tenant
          con gate por saldo de recargas IA de la suscripción.

        Tras instalar este pack, cada tenant ofrece chatbot en su sitio
        público. El consumo se cobra contra las recargas IA cargadas por
        Innatum admin, con margen snapshotteado al crear.
    """,
    'author': 'Innatum',
    'website': 'https://www.innatum.com',
    'category': 'Services',
    'version': '18.0.1.0.0',
    'depends': [
        'innatum_basico',
        'innatum_ai',
        'innatum_ai_web',
    ],
    'data': [],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
