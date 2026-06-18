# -*- coding: utf-8 -*-
{
    'name': 'Innatum SaaS — Suma Contabilidad',
    'summary': 'Agrega facturación electrónica EC y vínculo turno → factura',
    'description': """
        Módulo meta (sin código propio) que suma facturación al SaaS de
        agendamiento. Requiere innatum_basico instalado primero (se
        instala automáticamente como dependencia).

        Agrega:
        - innatum_agenda_facturacion: facturación electrónica para
          Ecuador (l10n_ec_edi), product asociado por servicio,
          generación de sale.order y account.move desde el turno.

        ⚠️ Solo aplica a tenants Ecuador. Para otros países, esperar a
        innatum_agenda_facturacion_ec genérico (Fase 5 del roadmap).
    """,
    'author': 'Innatum',
    'website': 'https://www.innatum.com',
    'category': 'Services',
    'version': '18.0.1.0.0',
    'depends': [
        'innatum_basico',
        'innatum_agenda_facturacion',
    ],
    'data': [],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
