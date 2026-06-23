# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ResCompany(models.Model):
    """Extiende res.company con datos del tenant SaaS WhatsApp.

    Estos campos se llenan al provisionar el tenant; el módulo los lee al
    procesar mensajes entrantes y armar respuestas al cliente.
    """
    _inherit = 'res.company'

    # Identificadores Meta (clave para multi-tenant routing)
    wa_phone_number_id = fields.Char(
        string='Meta Phone Number ID',
        help='Identificador del número WhatsApp Business asignado por Meta.',
    )
    wa_business_account_id = fields.Char(string='Meta WABA ID')

    # Vínculo con Supabase
    supabase_tenant_id = fields.Char(
        string='Supabase Tenant ID',
        help='UUID de la fila en public.tenants. Útil al debugear flujos.',
    )

    # Usuario dedicado del agente WhatsApp (trazabilidad + permisos quirúrgicos)
    wa_agent_user_id = fields.Many2one(
        'res.users',
        string='Usuario del agente WhatsApp',
        domain="[('share', '=', False)]",
        help='Usuario interno con el que el controller /api/whatsapp/message '
             'ejecuta las acciones (create/write turnos, partners, etc.). '
             'Debe tener el grupo Operador de Agenda para ver toda la agenda '
             'del tenant.',
    )

    # Perfil del negocio (1-a-1 con la compañía). Usado como One2many para
    # poder embeber el form del profile dentro de la vista de la empresa que
    # ve el tenant admin (Administración → Mi Negocio → Empresa).
    business_profile_ids = fields.One2many(
        'innatum.business.profile',
        'company_id',
        string='Perfil del negocio',
    )

    _sql_constraints = [
        ('wa_phone_number_id_unique',
         'UNIQUE(wa_phone_number_id)',
         'El Phone Number ID de Meta debe ser único entre empresas.'),
    ]

    def ensure_wa_agent_user(self):
        """Devuelve el wa_agent_user de la compañía; lo crea si no existe.

        El user se crea con grupos:
          - base.group_user (Usuario interno)
          - innatum_agenda_core.innatum_agenda_group_operator (ve toda la agenda)
        """
        self.ensure_one()
        if self.wa_agent_user_id:
            return self.wa_agent_user_id

        Users = self.env['res.users'].sudo()
        login = f'wa_agent_{self.id}@innatum.local'

        existing = Users.with_context(active_test=False).search([
            ('login', '=', login),
        ], limit=1)
        if existing:
            self.wa_agent_user_id = existing.id
            return existing

        try:
            group_operator = self.env.ref(
                'innatum_agenda_core.innatum_agenda_group_operator')
        except ValueError:
            group_operator = self.env['res.groups']
        group_user = self.env.ref('base.group_user')

        groups = group_user
        if group_operator:
            groups |= group_operator

        user = Users.create({
            'name': f'WhatsApp Bot ({self.name})',
            'login': login,
            'company_id': self.id,
            'company_ids': [(6, 0, [self.id])],
            'groups_id': [(6, 0, groups.ids)],
            'share': False,
            'notification_type': 'email',
        })
        self.wa_agent_user_id = user.id
        return user

    @api.constrains('wa_agent_user_id')
    def _check_wa_agent_user_company(self):
        for company in self:
            user = company.wa_agent_user_id
            if user and user.company_id and user.company_id.id != company.id:
                raise UserError(_(
                    'El usuario del agente WhatsApp debe pertenecer a esta '
                    'compañía (%(company)s).'
                ) % {'company': company.name})
