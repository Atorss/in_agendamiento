# -*- coding: utf-8 -*-
{
    'name': 'Innatum SaaS — Instalador',
    'summary': 'Instala el ambiente completo del SaaS de agendamiento Innatum '
               '(agenda, web, IA web, agente WhatsApp y facturación SRI)',
    'description': """
        Módulo meta (sin código propio) que instala TODO el stack del SaaS
        de agendamiento Innatum en una sola operación. En el modelo
        multi-tenant de BD compartida los módulos se instalan UNA vez para
        toda la BD; qué features ve cada empresa NO se decide instalando o
        desinstalando módulos por tenant (eso es imposible en BD compartida)
        sino por su SUSCRIPCIÓN (in_agenda.suscripcion → plan → feature flags).

        Stack instalado:
        - innatum_agenda_core: turnos, planificaciones, servicios,
          colaboradores, reglas multi-tenant.
        - innatum_agenda_admin: backend de gestión (app + appsbar).
        - innatum_agenda_planes: planes, suscripciones, recargas IA,
          wizard de provisioning de tenants y feature flags por plan.
        - innatum_agenda_web (+ web_odonto): sitio público de reserva.
        - innatum_ai / innatum_ai_web: chatbot IA del sitio público.
        - innatum_ai_core / innatum_flow_scheduling: agente de WhatsApp
          (tools de agendamiento vía n8n).
        - innatum_agenda_edi_sri: facturación electrónica Ecuador (envío al SRI).

        Cada feature (WhatsApp, IA web, facturación SRI) se habilita por
        empresa según el plan de su suscripción, en vivo.
    """,
    'author': 'Innatum',
    'website': 'https://www.innatum.com',
    'category': 'Services',
    'version': '18.0.2.0.0',
    'depends': [
        # Núcleo + backend
        'innatum_agenda_core',
        'innatum_agenda_admin',
        'innatum_agenda_planes',
        # Sitio público
        'innatum_agenda_web',
        'innatum_agenda_web_odonto',
        # IA: motor + agente WhatsApp + chatbot web + tools (módulo único)
        'innatum_agenda_ai',
        # Facturación electrónica SRI (Ecuador) — copia exclusiva del SaaS
        'innatum_agenda_edi_sri',
        # UI MuK (tema backend Innatum + utilidades). theme arrastra
        # chatter/dialog/appsbar/colors; group y refresh van explícitos.
        'muk_web_theme',
        'muk_web_group',
        'muk_web_refresh',
    ],
    'data': [
        'data/admin_groups.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
