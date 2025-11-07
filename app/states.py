from aiogram.fsm.state import State, StatesGroup

class BuyStates(StatesGroup):
    waiting_receipt = State()

class AdminStates(StatesGroup):
    waiting_message = State()

class ShopStates(StatesGroup):
    # AI
    ai_team_wait_email = State()
    ai_plus_wait_email = State()
    ai_plus_wait_password = State()
    # Telegram
    tg_premium_wait_id = State()
    # Requests
    ready_country_wait_text = State()
    buildbot_wait_requirements = State()
    other_wait_request = State()
    other_wait_attachment = State()

class CheckoutStates(StatesGroup):
    wait_card_receipt = State()
    wait_mixed_amount = State()
    wait_card_comment = State()
    wait_card_confirm = State()
    wait_wallet_comment = State()
    wait_wallet_confirm = State()
    wait_plan_comment = State()
    wait_plan_confirm = State()


class VerifyStates(StatesGroup):
    wait_contact = State()  # منتظر اشتراک شماره


class BuildBotStates(StatesGroup):
    wait_requirements = State()  # توضیحات مشتری برای ساخت بات


class ProfileStates(StatesGroup):
    wait_coupon_code = State()
