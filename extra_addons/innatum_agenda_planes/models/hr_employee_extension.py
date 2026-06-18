# -*- coding: utf-8 -*-
"""Enforcement de max_profesionales del plan.

Cuenta TODOS los hr.employee activos con company_id del tenant. Si exceden
el límite del plan vigente (max_profesionales > 0), bloquea con
ValidationError.

Constraint Python (en lugar de SQL) porque depende de un campo de plan
que está en otro módulo. Se dispara en create/write/active.
"""

from odoo import models, api, _
from odoo.exceptions import ValidationError


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    @api.constrains('company_id', 'active')
    def _check_plan_max_profesionales(self):
        Sus = self.env['in_agenda.suscripcion'].sudo()
        # Agrupar por company para no hacer N queries idénticas
        companies = self.mapped('company_id')
        for company in companies:
            # _ensure_active_for_company:
            #  - False  → company del sistema (sin límites)
            #  - susc   → aplicar límites del plan
            #  - raise  → company sin suscripción (no debería pasar en prod)
            susc = Sus._ensure_active_for_company(company)
            if not susc:
                continue  # sistema, sin límites
            limite = susc.plan_id.max_profesionales
            if not limite:
                continue  # plan ilimitado
            count = self.sudo().search_count([
                ('company_id', '=', company.id),
                ('active', '=', True),
            ])
            if count > limite:
                raise ValidationError(_(
                    'El plan "%(plan)s" permite máximo %(limite)d '
                    'profesional(es) para la empresa "%(company)s". '
                    'Tienes %(count)d.\n\n'
                    'Para aumentar este límite, contacta a Innatum para '
                    'cambiar de plan.',
                    plan=susc.plan_id.name,
                    limite=limite,
                    company=company.name,
                    count=count,
                ))
