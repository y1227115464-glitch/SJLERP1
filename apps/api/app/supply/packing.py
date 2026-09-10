from app.core.api import fail


def require_whole_cartons(quantity: int, units_per_carton: int | None) -> int:
    if units_per_carton is None or units_per_carton <= 0:
        fail(422, 'missing_carton_size', '请先维护商品箱规，或为本次发货填写箱规（件/箱）')
    if quantity % units_per_carton:
        fail(422, 'not_whole_cartons', f'发货数量 {quantity} 必须是本单箱规 {units_per_carton} 件/箱的整数倍')
    return units_per_carton
