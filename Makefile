# Deployment helpers for kann_ai_bot.
#
# Create a file called .uberspace in the repo root with:
#   UBERSPACE=youruser@xyz.uberspace.de
#
# Then use:
#   make setup      - first-time setup on the server
#   make deploy     - push and update running instances
#   make status     - show supervisord status for all 4 processes
#   make restart    - restart all 4 processes
#   make restart-web - restart web instances only
#   make logs-web-de / logs-web-en / logs-bot-de / logs-bot-en

-include .uberspace

ifndef UBERSPACE
$(error Create a .uberspace file with: UBERSPACE=youruser@xyz.uberspace.de)
endif

SSH = ssh $(UBERSPACE)
REMOTE_DIR = /home/$(shell echo $(UBERSPACE) | cut -d@ -f1)/repos/kann_ai_bot
LOG_DIR    = /home/$(shell echo $(UBERSPACE) | cut -d@ -f1)/repos/logs

.PHONY: setup deploy status restart restart-web restart-bots \
        logs-web-de logs-web-en logs-bot-de logs-bot-en seed-de seed-en

setup:
	$(SSH) "cd $(REMOTE_DIR) && bash deploy/setup.sh"

deploy:
	$(SSH) "cd $(REMOTE_DIR) && bash deploy/update.sh"

deploy-restart-bots:
	$(SSH) "cd $(REMOTE_DIR) && bash deploy/update.sh --restart-bots"

status:
	$(SSH) "supervisorctl status kann_ai_web_de kann_ai_bot_de kann_ai_web_en kann_ai_bot_en"

restart:
	$(SSH) "supervisorctl restart kann_ai_web_de kann_ai_bot_de kann_ai_web_en kann_ai_bot_en"

restart-web:
	$(SSH) "supervisorctl restart kann_ai_web_de kann_ai_web_en"

restart-bots:
	$(SSH) "supervisorctl restart kann_ai_bot_de kann_ai_bot_en"

logs-web-de:
	$(SSH) "tail -f $(LOG_DIR)/kann_ai_web_de.log"

logs-web-en:
	$(SSH) "tail -f $(LOG_DIR)/kann_ai_web_en.log"

logs-bot-de:
	$(SSH) "tail -f $(LOG_DIR)/kann_ai_bot_de.log"

logs-bot-en:
	$(SSH) "tail -f $(LOG_DIR)/kann_ai_bot_en.log"

# Seed fake data for testing (requires .env.de / .env.en on the server)
seed-de:
	$(SSH) "cd $(REMOTE_DIR) && DOTENV_PATH=$(REMOTE_DIR)/.env.de uv run python seed_fake_data.py"

seed-en:
	$(SSH) "cd $(REMOTE_DIR) && DOTENV_PATH=$(REMOTE_DIR)/.env.en uv run python seed_fake_data.py"
