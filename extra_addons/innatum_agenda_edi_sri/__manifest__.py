{
    'name': 'Innatum Agenda — Facturación Electrónica SRI',
    'summary': 'Emisión, firma XAdES-BES y envío de comprobantes electrónicos al SRI '
               '(copia exclusiva del SaaS de agendamiento, con gate por suscripción)',
    'description': """
Facturación Electrónica SRI (Ecuador)
=====================================

Módulo propio (IP Innatum) para emitir comprobantes electrónicos al SRI bajo
el esquema offline. Construido sobre Odoo Community (account + l10n_ec), sin
dependencias de Odoo Enterprise ni de terceros propietarios.

Implementa, desde cero según la Ficha Técnica oficial del SRI:

* Clave de acceso de 49 dígitos con dígito verificador (módulo 11).
* Generación del XML de la factura (versión 1.1.0) a partir de account.move.
* Firma electrónica XAdES-BES (RSA-SHA1, C14N, enveloped) a nivel de compañía,
  con certificado .p12 cifrado.
* Envío asíncrono a los web services de Recepción y Autorización (pruebas/prod).
* RIDE (representación impresa) en PDF.

Multi-compañía: cada compañía gestiona su propio certificado, ambiente y
numeración. Diseñado para operación SaaS multi-tenant.
""",
    'author': 'Innatum',
    'website': 'https://www.innatum.com',
    'category': 'Accounting/Localizations/EDI',
    'version': '18.0.1.3.0',
    'depends': [
        'account',
        'l10n_ec',
        'innatum_agenda_admin',
    ],
    'external_dependencies': {
        'python': [
            'cryptography',
            'lxml',
            'zeep',
        ],
    },
    'data': [
        'security/ir.model.access.csv',
        'security/in_edi_sri_rules.xml',
        'data/ir_cron.xml',
        'views/in_edi_certificate_views.xml',
        'views/res_config_settings_views.xml',
        'views/account_journal_views.xml',
        'views/account_move_views.xml',
        'views/in_edi_document_views.xml',
        'views/res_company_empresa_sri_inherit.xml',
        'report/ride_factura_report.xml',
        'report/ride_factura_templates.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
