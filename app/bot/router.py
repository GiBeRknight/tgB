from app.bot.handlers.admin import router as admin_router
from app.bot.handlers.auth import router as auth_router
from app.bot.handlers.plots import router as plots_router

routers = (auth_router, plots_router, admin_router)
