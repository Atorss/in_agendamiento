# -*- coding: utf-8 -*-
"""Extensión del wizard de provisioning para integrar el agente WhatsApp.

Hereda `in_agenda.tenant.wizard` (definido en innatum_agenda_planes) y agrega:
  - Campos transient para credenciales Meta (wa_phone_number_id, wa_business_account_id)
  - Campo transient para Supabase Tenant ID (UUID)
  - Campo transient para vertical_template_id (necesario para crear business_profile)
  - Campo transient para bot_name + payment_policy (defaults del business_profile)

En `action_provision_tenant`:
  1. Llama al super() (crea company, website, admin user, suscripción, etc.)
  2. Localiza la company recién creada por el website.domain (que es único)
  3. Aplica los campos WhatsApp en res.company
  4. Crea innatum.business.profile vinculado a la company con el vertical
     elegido y los defaults del agente

Si cualquier paso falla, la transacción hace rollback completo (incluida la
parte del super), gracias a que el método corre dentro de una sola transacción
de wizard.
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class InAgendaTenantWizardExt(models.TransientModel):
    _inherit = 'in_agenda.tenant.wizard'

    # ------------------------------------------------------------------
    # Credenciales técnicas (Meta + Supabase) — configuradas por Innatum staff
    # ------------------------------------------------------------------

    wa_phone_number_id = fields.Char(
        string='Meta Phone Number ID',
        help='Identificador del número WhatsApp Business asignado por Meta. '
             'Dejá vacío si todavía no configurás WhatsApp para este tenant.',
    )
    wa_business_account_id = fields.Char(
        string='Meta WABA ID',
        help='WhatsApp Business Account ID de Meta.',
    )
    supabase_tenant_id = fields.Char(
        string='Supabase Tenant ID (UUID)',
        help='UUID de la fila correspondiente en public.tenants de Supabase. '
             'Se obtiene tras hacer el INSERT en Supabase.',
    )

    # ------------------------------------------------------------------
    # Configuración del agente IA — defaults del business_profile
    # ------------------------------------------------------------------

    vertical_template_id = fields.Many2one(
        'innatum.vertical.template',
        string='Vertical (tipo de negocio)',
        required=True,
        help='Odontología, Spa, Peluquería, etc. Define los defaults del '
             'agente para este vertical. El tenant admin puede editarlo después.',
    )
    bot_name = fields.Char(
        string='Nombre del agente',
        help='Cómo se presenta el bot ante el cliente. Ej: "Sofía". '
             'Opcional: si vacío, el tenant admin lo configura después.',
    )
    payment_policy_initial = fields.Selection([
        ('sin_cobro', 'Sin cobro previo'),
        ('anticipo', 'Anticipo configurable'),
        ('pago_total', 'Pago total para confirmar'),
    ],
        string='Política de cobro inicial',
        default='sin_cobro',
        required=True,
        help='Configurable después en el business_profile del tenant.',
    )

    # ------------------------------------------------------------------
    # Override del provisioning
    # ------------------------------------------------------------------

    def action_provision_tenant(self):
        """Provisiona el tenant + integra el agente WhatsApp.

        Llama al super() para que cree los artefactos core (company, website,
        admin user, suscripción, hr.employee opcional). Después aplica los
        campos del agente WhatsApp y crea el business_profile.
        """
        self.ensure_one()

        # Validar campos del agente antes de invocar al super para fallar rápido.
        if not self.vertical_template_id:
            raise UserError(_(
                'Tenés que elegir un vertical (tipo de negocio) para que el '
                'agente IA tenga un perfil válido.'
            ))

        # 1. Invocar al super → crea company, website, admin, suscripción, etc.
        result = super().action_provision_tenant()

        # 2. Localizar la company creada por el website.domain (único).
        full_domain = '%s://%s.%s' % (
            self.domain_scheme, self.subdomain, self.base_domain,
        )
        website = self.env['website'].sudo().search(
            [('domain', '=', full_domain)], limit=1,
        )
        if not website or not website.company_id:
            _logger.error(
                'No se pudo localizar la company recién creada (domain=%s)',
                full_domain,
            )
            # No abortamos — el super ya creó lo crítico. Solo skipeamos
            # la configuración del agente y dejamos un log.
            return result
        company = website.company_id

        # 3. Aplicar campos WhatsApp en res.company (todos opcionales).
        company_updates = {}
        if self.wa_phone_number_id:
            company_updates['wa_phone_number_id'] = self.wa_phone_number_id.strip()
        if self.wa_business_account_id:
            company_updates['wa_business_account_id'] = self.wa_business_account_id.strip()
        if self.supabase_tenant_id:
            company_updates['supabase_tenant_id'] = self.supabase_tenant_id.strip()
        if company_updates:
            company.sudo().write(company_updates)
            _logger.info(
                'Provisioning: campos Meta/Supabase aplicados a company=%s: %s',
                company.id, list(company_updates.keys()),
            )

        # 4. Crear el business_profile vinculado al tenant.
        existing_profile = self.env['innatum.business.profile'].sudo().search(
            [('company_id', '=', company.id)], limit=1,
        )
        if existing_profile:
            _logger.warning(
                'Provisioning: la company %s ya tiene business_profile (id=%s); skip',
                company.id, existing_profile.id,
            )
        else:
            profile_vals = {
                'company_id': company.id,
                'vertical_template_id': self.vertical_template_id.id,
                'payment_policy': self.payment_policy_initial or 'sin_cobro',
            }
            if self.bot_name:
                profile_vals['bot_name'] = self.bot_name.strip()
            profile = self.env['innatum.business.profile'].sudo().create(profile_vals)
            _logger.info(
                'Provisioning: business_profile creado (id=%s) para company=%s',
                profile.id, company.id,
            )

        return result
