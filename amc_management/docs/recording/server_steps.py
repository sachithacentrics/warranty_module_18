# Server-side steps of the recording done as other users (run through run_with_conf.py).
import base64
import json
import os
from datetime import timedelta

from odoo import Command, fields

env = env  # noqa: F821
step = os.environ['AMC_STEP']
params = json.loads(os.environ['AMC_PARAMS'])
SIGNATURE = base64.b64encode(
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00'
    b'\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00'
    b'\x00\x00\x00IEND\xaeB`\x82')
manager = env['res.users'].search([('login', '=', 'service.manager')])
tech = env.ref('base.user_demo')

if step == 'approve':
    case = env['warranty.case'].browse(params['case_id'])
    if case.state == 'eligibility_checked':
        case.with_user(manager).action_approve_case()
    print('STEP approve', case.name, case.state)
elif step == 'plan_job':
    job = env['warranty.service.job'].browse(params['job_id'])
    job.write({'planned_date': fields.Datetime.now() + timedelta(hours=3),
               'main_technician_id': tech.id})
    print('STEP plan', job.name, job.state)
elif step == 'complete_job':
    job = env['warranty.service.job'].browse(params['job_id'])
    task = job.visit_ids[:1]
    task.with_user(tech).action_timer_start()
    action = task.with_user(tech).action_timer_stop()
    wizard = env[action['res_model']].with_user(tech).with_context(action['context']).create(
        {'time_spent': 1.0, 'description': 'Preventive maintenance: filters, coils, gas pressure'})
    wizard.save_timesheet()
    task.sudo().write({'worksheet_signature': SIGNATURE, 'worksheet_signed_by': 'Wood Corner'})
    job.visit_ids.with_user(tech).action_warranty_complete_visit()
    print('STEP complete', job.name, job.state, job.amc_visit_ids.mapped('state'))
env.cr.commit()
