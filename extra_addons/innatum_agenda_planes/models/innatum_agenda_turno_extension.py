# -*- coding: utf-8 -*-
"""Enforcement de max_turnos_mes del plan.

Cuenta turnos creados (cualquier estado) en el mes calendario actual,
basado en create_date. Si exceden el límite del plan, bloquea con
ValidationError.

Se valida en create (no en write) porque "generar turnos" es la operación
que consume cuota. Mover un turno existente no incrementa el count.
"""

from collections import defaultdict
from datetime import datetime

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class InnatumAgendaTurno(models.Model):
    _inherit = 'innatum.agenda.turno'

    @api.model_create_multi
    def create(self, vals_list):
        self._check_plan_max_turnos_mes(vals_list)
        return super().create(vals_list)

    @api.model
    def _check_plan_max_turnos_mes(self, vals_list):
        """Valida que el batch no exceda el límite mensual del plan.

        Resuelve company_id desde professional_id (campo related en el
        modelo) si no viene explícito en vals.
        """
        Sus = self.env['in_agenda.suscripcion'].sudo()
        Employee = self.env['hr.employee'].sudo()

        # Conteo de turnos NUEVOS por company en este batch
        new_by_company = defaultdict(int)
        for vals in vals_list:
            company_id = vals.get('company_id')
            if not company_id and vals.get('professional_id'):
                # company_id es related store=True de professional_id
                emp = Employee.browse(vals['professional_id'])
                company_id = emp.company_id.id
            if company_id:
                new_by_company[company_id] += 1

        if not new_by_company:
            return

        # Inicio del mes actual (con hora 00:00:00)
        hoy = fields.Date.today()
        primer_dia = hoy.replace(day=1)
        primer_dia_dt = datetime.combine(primer_dia, datetime.min.time())

        Company = self.env['res.company'].sudo()
        for company_id, count_new in new_by_company.items():
            company = Company.browse(company_id)
            susc = Sus._ensure_active_for_company(company)
            if not susc:
                continue  # sistema, sin límites
            limite = susc.plan_id.max_turnos_mes
            if not limite:
                continue  # plan ilimitado
            count_existentes = self.sudo().search_count([
                ('company_id', '=', company_id),
                ('create_date', '>=', primer_dia_dt),
            ])
            if count_existentes + count_new > limite:
                raise ValidationError(_(
                    'El plan "%(plan)s" permite %(limite)d turnos por mes '
                    'para la empresa "%(company)s".\n'
                    'Ya generaste %(count)d este mes y querés crear '
                    '%(new)d más.\n\n'
                    'Para aumentar este límite, contacta a Innatum para '
                    'cambiar de plan.',
                    plan=susc.plan_id.name,
                    limite=limite,
                    company=company.name,
                    count=count_existentes,
                    new=count_new,
                ))
