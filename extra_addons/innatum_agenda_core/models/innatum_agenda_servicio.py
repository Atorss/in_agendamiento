# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError


class InnatumAgendaServicio(models.Model):
    """Catálogo centralizado de servicios del SaaS.

    Los servicios son gestionados por Innatum (catálogo global) y se asignan
    a uno o más tenants vía company_ids (M2M). El admin del tenant solo VE
    los servicios que Innatum le habilitó; no puede crear ni editar.

    Esto garantiza consistencia cross-tenant: el código "CORTE" significa
    "Corte de pelo" en TODOS los tenants que lo ofrecen, simplificando
    analytics, chatbot IA y onboarding (Innatum tilda servicios al
    provisionar un tenant nuevo).
    """
    _name = 'innatum.agenda.servicio'
    _description = 'Servicio (catálogo)'
    _order = 'name'

    name = fields.Char(string='Nombre', required=True)
    code = fields.Char(string='Código', required=True)
    description = fields.Text(string='Descripción')
    active = fields.Boolean(default=True)
    image_1920 = fields.Image(
        string='Imagen',
        max_width=1920,
        max_height=1920,
        help='Imagen opcional del servicio. Si se define, el sitio público '
             'la muestra en la tarjeta del servicio; si no, se muestra solo '
             'el nombre.',
    )

    company_ids = fields.Many2many(
        'res.company',
        'innatum_agenda_servicio_company_rel',
        'servicio_id', 'company_id',
        string='Tenants habilitados',
        help='Tenants (companies) que pueden ofrecer este servicio. '
             'Innatum decide qué servicios habilita para cada tenant.',
    )

    _sql_constraints = [
        ('code_unique', 'unique(code)',
         'El código del servicio debe ser único en el catálogo.'),
    ]

    @api.model
    def _search(self, domain, offset=0, limit=None, order=None):
        """Filtra el catálogo por el perfil del usuario cuando se solicita
        explícitamente con el contexto `servicios_por_rol` (se activa en el
        selector de servicios de la planificación). Server-side y confiable —
        a diferencia de un dominio sobre un campo computado, el dropdown
        (que usa name_search → _search) siempre lo respeta.

        - Administrador del tenant: ve todos los servicios habilitados para su
          compañía (sin filtro extra; el acceso ya está acotado a la company).
        - Operador / Usuario: solo los servicios asignados en su ficha de
          personal (hr.employee.servicio_ids).
        """
        if self.env.context.get('servicios_por_rol') and not self.env.su:
            is_admin = self.env.user.has_group(
                'innatum_agenda_core.innatum_agenda_group_admin')
            if not is_admin:
                emp = self.env['hr.employee'].sudo().search(
                    [('user_id', '=', self.env.uid)], limit=1)
                domain = list(domain or []) + [
                    ('id', 'in', emp.servicio_ids.ids)]
        return super()._search(domain, offset=offset, limit=limit, order=order)

    def unlink(self):
        if not self.env.user.has_group(
            'innatum_agenda_core.innatum_agenda_group_admin'
        ) and not self.env.user.has_group('base.group_system'):
            raise ValidationError(
                "Los servicios del catálogo solo pueden ser eliminados "
                "por administradores Innatum."
            )
        return super().unlink()
