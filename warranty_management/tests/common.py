def confirm_and_group(order, grouping_mode='per_so'):
    """Confirm the Sales Order and create its Draft Warranty Cards through the Warranty
    Grouping wizard with `grouping_mode` (when warranty products are pending)."""
    order.action_confirm()
    if not order.warranty_grouping_pending:
        return order
    wizard = order.env['warranty.grouping.wizard'].with_context(
        default_sale_order_id=order.id).create({'card_grouping_mode': grouping_mode})
    wizard.action_confirm()
    return order


def set_installation(card, installation_date):
    """Installation basis without an installation Field Service task (Start Date Automation):
    the installation date is recorded as an authorized exception (Warranty: Date Correction);
    the card is then confirmed manually. Other start criteria do not use the installation
    date."""
    if card.start_criterion == 'installation':
        card.sudo()._warranty_apply_exception(installation_date, "Test installation date")
    return card
