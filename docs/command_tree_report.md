# Command Tree Validation Report

- Commands discovered: **252**
- Errors: **0**
- Warnings: **42**

## Inventory

| Root | Subgroup | Action | Description | Source |
| --- | --- | --- | --- | --- |
| `attivita` | `—` | `ieri` | Report attività di ieri (DM staff) | `app/plugins/commands_modular/attivita.py:600` |
| `attivita` | `—` | `oggi` | Report attività di oggi (DM staff) | `app/plugins/commands_modular/attivita.py:595` |
| `attivita` | `—` | `range` | Report attività per range custom | `app/plugins/commands_modular/attivita.py:625` |
| `attivita` | `—` | `ultimi` | Report attività ultimi N periodi | `app/plugins/commands_modular/attivita.py:613` |
| `audionotes` | `—` | `config_reset` | Reset the audio notes configuration to defaults. | `app/plugins/commands_modular/audio_notes.py:168` |
| `audionotes` | `—` | `config_set` | Update the audio notes configuration. | `app/plugins/commands_modular/audio_notes.py:83` |
| `audionotes` | `—` | `config_show` | Show the audio notes configuration. | `app/plugins/commands_modular/audio_notes.py:149` |
| `audionotes` | `—` | `off` | Disable audio notes. | `app/plugins/commands_modular/audio_notes.py:41` |
| `audionotes` | `—` | `on` | Enable audio notes. | `app/plugins/commands_modular/audio_notes.py:27` |
| `audionotes` | `—` | `status` | Show the audio notes status. | `app/plugins/commands_modular/audio_notes.py:55` |
| `aura` | `—` | `ieri` | Aura di ieri | `app/plugins/commands_modular/aura.py:457` |
| `aura` | `—` | `oggi` | Aura di oggi | `app/plugins/commands_modular/aura.py:452` |
| `aura` | `—` | `range` | Aura per intervallo | `app/plugins/commands_modular/aura.py:463` |
| `aura` | `—` | `ultimi` | Aura ultimi N periodi | `app/plugins/commands_modular/aura.py:435` |
| `bm` | `ai` | `fallback_set` | Set the AI fallback model for a task. | `app/plugins/commands_modular/admin.py:606` |
| `bm` | `ai` | `fallback_show` | Show configured AI fallback models. | `app/plugins/commands_modular/admin.py:637` |
| `bm` | `ai` | `model_set` | Set the AI model for a task. | `app/plugins/commands_modular/admin.py:561` |
| `bm` | `ai` | `model_show` | Show configured AI models. | `app/plugins/commands_modular/admin.py:592` |
| `bm` | `ai` | `off` | Disable the AI service. | `app/plugins/commands_modular/admin.py:551` |
| `bm` | `ai` | `on` | Enable the AI service. | `app/plugins/commands_modular/admin.py:544` |
| `bm` | `ai` | `run` | Run an AI test prompt. | `app/plugins/commands_modular/admin.py:683` |
| `bm` | `ai` | `status` | Show AI service status. | `app/plugins/commands_modular/admin.py:648` |
| `bm` | `backfill` | `config_reset` | Reset backfill configuration to defaults. | `app/plugins/commands_modular/admin.py:503` |
| `bm` | `backfill` | `config_set` | Update backfill configuration. | `app/plugins/commands_modular/admin.py:456` |
| `bm` | `backfill` | `config_show` | Show backfill configuration. | `app/plugins/commands_modular/admin.py:491` |
| `bm` | `backfill` | `off` | Disable backfill. | `app/plugins/commands_modular/admin.py:434` |
| `bm` | `backfill` | `on` | Enable backfill. | `app/plugins/commands_modular/admin.py:427` |
| `bm` | `backfill` | `run` | Run backfill now. | `app/plugins/commands_modular/admin.py:518` |
| `bm` | `backfill` | `status` | Show backfill status. | `app/plugins/commands_modular/admin.py:441` |
| `bm` | `barcello` | `calibrate` | Recalculate Barcello calibration weights. | `app/plugins/commands_modular/barcello.py:224` |
| `bm` | `barcello` | `mood_reset` | Reset the Barcello mood for this channel. | `app/plugins/commands_modular/barcello.py:213` |
| `bm` | `barcello` | `mood_set` | Set the Barcello mood for this channel. | `app/plugins/commands_modular/barcello.py:180` |
| `bm` | `barcello` | `mood_show` | Show the Barcello mood for this channel. | `app/plugins/commands_modular/barcello.py:209` |
| `bm` | `barcello` | `off` | Disable the Barcello trigger for this channel. | `app/plugins/commands_modular/barcello.py:171` |
| `bm` | `barcello` | `on` | Enable the Barcello trigger for this channel. | `app/plugins/commands_modular/barcello.py:167` |
| `bm` | `barcello` | `run` | Run the Barcello analysis. | `app/plugins/commands_modular/barcello.py:1095` |
| `bm` | `barcello` | `status` | Show Barcello trigger status for this channel. | `app/plugins/commands_modular/barcello.py:175` |
| `bm` | `events` | `off` | Disable event collection for this channel. | `app/plugins/commands_modular/admin.py:324` |
| `bm` | `events` | `on` | Enable event collection for this channel. | `app/plugins/commands_modular/admin.py:318` |
| `bm` | `events` | `status` | Show event collection status for this channel. | `app/plugins/commands_modular/admin.py:330` |
| `bm` | `footer` | `off` | Disable footer rendering. | `app/plugins/commands_modular/admin.py:724` |
| `bm` | `footer` | `on` | Enable footer rendering. | `app/plugins/commands_modular/admin.py:714` |
| `bm` | `footer` | `status` | Show footer status and rendered variants. | `app/plugins/commands_modular/admin.py:853` |
| `bm` | `footer` | `template_global_reset` | Reset the global footer template. | `app/plugins/commands_modular/admin.py:787` |
| `bm` | `footer` | `template_global_set` | Set the global footer template. | `app/plugins/commands_modular/admin.py:735` |
| `bm` | `footer` | `template_global_show` | Show the global footer template. | `app/plugins/commands_modular/admin.py:770` |
| `bm` | `footer` | `template_service_reset` | Reset a service-specific footer template. | `app/plugins/commands_modular/admin.py:839` |
| `bm` | `footer` | `template_service_set` | Set a service-specific footer template. | `app/plugins/commands_modular/admin.py:799` |
| `bm` | `footer` | `template_service_show` | Show a service-specific footer template. | `app/plugins/commands_modular/admin.py:818` |
| `bm` | `retention` | `config_reset` | Reset retention configuration to defaults. | `app/plugins/commands_modular/admin.py:412` |
| `bm` | `retention` | `config_set` | Update retention configuration. | `app/plugins/commands_modular/admin.py:365` |
| `bm` | `retention` | `config_show` | Show retention configuration. | `app/plugins/commands_modular/admin.py:400` |
| `bm` | `retention` | `off` | Disable the retention task. | `app/plugins/commands_modular/admin.py:343` |
| `bm` | `retention` | `on` | Enable the retention task. | `app/plugins/commands_modular/admin.py:336` |
| `bm` | `retention` | `status` | Show retention status. | `app/plugins/commands_modular/admin.py:350` |
| `bm` | `—` | `status` | Show the Barcellometro status. | `app/plugins/commands_modular/status.py:15` |
| `campagne` | `cap` | `config_reset` | Reset the daily cap configuration | `app/plugins/commands_modular/messaggi.py:537` |
| `campagne` | `cap` | `config_set` | Set the daily cap configuration | `app/plugins/commands_modular/messaggi.py:520` |
| `campagne` | `cap` | `config_show` | Show the daily cap configuration | `app/plugins/commands_modular/messaggi.py:530` |
| `campagne` | `cap` | `off` | Disable the daily cap | `app/plugins/commands_modular/messaggi.py:504` |
| `campagne` | `cap` | `on` | Enable the daily cap | `app/plugins/commands_modular/messaggi.py:497` |
| `campagne` | `cap` | `status` | Show the daily cap status | `app/plugins/commands_modular/messaggi.py:511` |
| `campagne` | `custom` | `entry_add` | Add a custom campaign entry | `app/plugins/commands_modular/messaggi.py:571` |
| `campagne` | `custom` | `entry_edit` | Edit a custom campaign entry | `app/plugins/commands_modular/messaggi.py:725` |
| `campagne` | `custom` | `entry_list` | List custom campaign entries | `app/plugins/commands_modular/messaggi.py:641` |
| `campagne` | `custom` | `entry_remove` | Remove a custom campaign entry | `app/plugins/commands_modular/messaggi.py:669` |
| `campagne` | `custom` | `entry_run` | Run a custom campaign entry now | `app/plugins/commands_modular/messaggi.py:684` |
| `campagne` | `custom` | `entry_show` | Show a custom campaign entry | `app/plugins/commands_modular/messaggi.py:655` |
| `campagne` | `custom` | `off` | Disable custom campaigns in the current channel | `app/plugins/commands_modular/messaggi.py:548` |
| `campagne` | `custom` | `on` | Enable custom campaigns in the current channel | `app/plugins/commands_modular/messaggi.py:544` |
| `campagne` | `custom` | `status` | Show custom campaign status for the current channel | `app/plugins/commands_modular/messaggi.py:552` |
| `campagne` | `horoscope` | `config_reset` | Reset the horoscope campaign configuration | `app/plugins/commands_modular/messaggi.py:983` |
| `campagne` | `horoscope` | `config_set` | Create or update the horoscope campaign configuration | `app/plugins/commands_modular/messaggi.py:958` |
| `campagne` | `horoscope` | `config_show` | Show the horoscope campaign configuration | `app/plugins/commands_modular/messaggi.py:979` |
| `campagne` | `horoscope` | `off` | Disable horoscope campaigns in the current channel | `app/plugins/commands_modular/messaggi.py:943` |
| `campagne` | `horoscope` | `on` | Enable horoscope campaigns in the current channel | `app/plugins/commands_modular/messaggi.py:939` |
| `campagne` | `horoscope` | `run` | Run the horoscope campaign immediately | `app/plugins/commands_modular/messaggi.py:987` |
| `campagne` | `horoscope` | `status` | Show horoscope campaign status for the current channel | `app/plugins/commands_modular/messaggi.py:947` |
| `campagne` | `news` | `config_reset` | Reset the news campaign configuration | `app/plugins/commands_modular/messaggi.py:879` |
| `campagne` | `news` | `config_set` | Create or update the news campaign configuration | `app/plugins/commands_modular/messaggi.py:853` |
| `campagne` | `news` | `config_show` | Show the news campaign configuration | `app/plugins/commands_modular/messaggi.py:875` |
| `campagne` | `news` | `off` | Disable news campaigns in the current channel | `app/plugins/commands_modular/messaggi.py:837` |
| `campagne` | `news` | `on` | Enable news campaigns in the current channel | `app/plugins/commands_modular/messaggi.py:833` |
| `campagne` | `news` | `run` | Run the news campaign immediately | `app/plugins/commands_modular/messaggi.py:883` |
| `campagne` | `news` | `status` | Show news campaign status for the current channel | `app/plugins/commands_modular/messaggi.py:841` |
| `campagne` | `—` | `off` | Disable campaigns in the current channel | `app/plugins/commands_modular/messaggi.py:425` |
| `campagne` | `—` | `on` | Enable campaigns in the current channel | `app/plugins/commands_modular/messaggi.py:414` |
| `campagne` | `prompt` | `entry_add` | Add a prompt campaign entry | `app/plugins/commands_modular/triggers.py:603` |
| `campagne` | `prompt` | `entry_edit` | Edit a prompt campaign entry | `app/plugins/commands_modular/triggers.py:751` |
| `campagne` | `prompt` | `entry_list` | List prompt campaign entries | `app/plugins/commands_modular/triggers.py:662` |
| `campagne` | `prompt` | `entry_remove` | Remove a prompt campaign entry | `app/plugins/commands_modular/triggers.py:692` |
| `campagne` | `prompt` | `entry_run` | Run a prompt campaign entry now | `app/plugins/commands_modular/triggers.py:707` |
| `campagne` | `prompt` | `entry_show` | Show a prompt campaign entry | `app/plugins/commands_modular/triggers.py:677` |
| `campagne` | `prompt` | `off` | Disable prompt campaigns in the current channel | `app/plugins/commands_modular/triggers.py:572` |
| `campagne` | `prompt` | `on` | Enable prompt campaigns in the current channel | `app/plugins/commands_modular/triggers.py:560` |
| `campagne` | `prompt` | `status` | Show prompt campaign status for the current channel | `app/plugins/commands_modular/triggers.py:584` |
| `campagne` | `quiet` | `config_reset` | Reset quiet hours configuration | `app/plugins/commands_modular/messaggi.py:489` |
| `campagne` | `quiet` | `config_set` | Set quiet hours configuration | `app/plugins/commands_modular/messaggi.py:473` |
| `campagne` | `quiet` | `config_show` | Show quiet hours configuration | `app/plugins/commands_modular/messaggi.py:481` |
| `campagne` | `quiet` | `off` | Disable quiet hours | `app/plugins/commands_modular/messaggi.py:456` |
| `campagne` | `quiet` | `on` | Enable quiet hours | `app/plugins/commands_modular/messaggi.py:449` |
| `campagne` | `quiet` | `status` | Show quiet hours status | `app/plugins/commands_modular/messaggi.py:463` |
| `campagne` | `—` | `status` | Show campaign status for the current channel | `app/plugins/commands_modular/messaggi.py:436` |
| `campagne` | `weather` | `config_reset` | Reset the weather campaign configuration | `app/plugins/commands_modular/messaggi.py:931` |
| `campagne` | `weather` | `config_set` | Create or update the weather campaign configuration | `app/plugins/commands_modular/messaggi.py:906` |
| `campagne` | `weather` | `config_show` | Show the weather campaign configuration | `app/plugins/commands_modular/messaggi.py:927` |
| `campagne` | `weather` | `off` | Disable weather campaigns in the current channel | `app/plugins/commands_modular/messaggi.py:891` |
| `campagne` | `weather` | `on` | Enable weather campaigns in the current channel | `app/plugins/commands_modular/messaggi.py:887` |
| `campagne` | `weather` | `run` | Run the weather campaign immediately | `app/plugins/commands_modular/messaggi.py:935` |
| `campagne` | `weather` | `status` | Show weather campaign status for the current channel | `app/plugins/commands_modular/messaggi.py:895` |
| `commandguard` | `—` | `role_add` | Add a role command policy. | `app/plugins/commands_modular/roles.py:48` |
| `commandguard` | `—` | `role_edit` | Edit a role command policy. | `app/plugins/commands_modular/roles.py:58` |
| `commandguard` | `—` | `role_list` | List all role policies. | `app/plugins/commands_modular/roles.py:88` |
| `commandguard` | `—` | `role_remove` | Remove a role command policy. | `app/plugins/commands_modular/roles.py:68` |
| `commandguard` | `—` | `role_reset` | Reset all policies for a role. | `app/plugins/commands_modular/roles.py:99` |
| `commandguard` | `—` | `role_show` | Show role policies. | `app/plugins/commands_modular/roles.py:76` |
| `commandguard` | `—` | `user_add` | Add a user command policy. | `app/plugins/commands_modular/roles.py:107` |
| `commandguard` | `—` | `user_edit` | Edit a user command policy. | `app/plugins/commands_modular/roles.py:117` |
| `commandguard` | `—` | `user_list` | List all user policies. | `app/plugins/commands_modular/roles.py:147` |
| `commandguard` | `—` | `user_remove` | Remove a user command policy. | `app/plugins/commands_modular/roles.py:127` |
| `commandguard` | `—` | `user_reset` | Reset all policies for a user. | `app/plugins/commands_modular/roles.py:158` |
| `commandguard` | `—` | `user_show` | Show user policies. | `app/plugins/commands_modular/roles.py:135` |
| `domanda` | `—` | `domanda` | Fai una domanda al Q&A | `app/plugins/commands_modular/ask.py:60` |
| `frasi` | `—` | `entry_add` | Add a phrase trigger entry | `app/plugins/commands_modular/triggers.py:249` |
| `frasi` | `—` | `entry_edit` | Edit a phrase trigger entry | `app/plugins/commands_modular/triggers.py:358` |
| `frasi` | `—` | `entry_list` | List phrase trigger entries | `app/plugins/commands_modular/triggers.py:304` |
| `frasi` | `—` | `entry_remove` | Remove a phrase trigger entry | `app/plugins/commands_modular/triggers.py:291` |
| `frasi` | `—` | `entry_show` | Show a phrase trigger entry | `app/plugins/commands_modular/triggers.py:317` |
| `frasi` | `—` | `off` | Disable phrase triggers | `app/plugins/commands_modular/triggers.py:233` |
| `frasi` | `—` | `on` | Enable phrase triggers | `app/plugins/commands_modular/triggers.py:229` |
| `frasi` | `—` | `status` | Show phrase trigger status | `app/plugins/commands_modular/triggers.py:237` |
| `frasi` | `—` | `template_global_reset` | Reset the global phrase template | `app/plugins/commands_modular/triggers.py:501` |
| `frasi` | `—` | `template_global_set` | Set the global phrase template | `app/plugins/commands_modular/triggers.py:474` |
| `frasi` | `—` | `template_global_show` | Show the global phrase template | `app/plugins/commands_modular/triggers.py:488` |
| `frasi` | `—` | `template_milestone_reset` | Reset all milestone templates | `app/plugins/commands_modular/triggers.py:461` |
| `frasi` | `—` | `template_milestone_set` | Create or update a milestone template | `app/plugins/commands_modular/triggers.py:431` |
| `frasi` | `—` | `template_milestone_show` | Show milestone templates | `app/plugins/commands_modular/triggers.py:448` |
| `frasi` | `—` | `template_user_reset` | Reset a user-specific phrase template | `app/plugins/commands_modular/triggers.py:549` |
| `frasi` | `—` | `template_user_set` | Set a user-specific phrase template | `app/plugins/commands_modular/triggers.py:519` |
| `frasi` | `—` | `template_user_show` | Show a user-specific phrase template | `app/plugins/commands_modular/triggers.py:536` |
| `inactivity` | `autokick` | `off` | Disable automatic inactivity actions. | `app/plugins/commands_modular/inattivi.py:225` |
| `inactivity` | `autokick` | `on` | Enable automatic inactivity actions. | `app/plugins/commands_modular/inattivi.py:218` |
| `inactivity` | `autokick` | `status` | Show the automatic inactivity action status. | `app/plugins/commands_modular/inattivi.py:232` |
| `inactivity` | `dms` | `cooldown_reset` | Reset the reminder DM cooldown. | `app/plugins/commands_modular/inattivi.py:377` |
| `inactivity` | `dms` | `cooldown_set` | Set the reminder DM cooldown. | `app/plugins/commands_modular/inattivi.py:363` |
| `inactivity` | `dms` | `cooldown_show` | Show the reminder DM cooldown. | `app/plugins/commands_modular/inattivi.py:370` |
| `inactivity` | `dms` | `invite_reset` | Reset the invite link used in inactivity DMs. | `app/plugins/commands_modular/inattivi.py:402` |
| `inactivity` | `dms` | `invite_set` | Set the invite link used in inactivity DMs. | `app/plugins/commands_modular/inattivi.py:388` |
| `inactivity` | `dms` | `invite_show` | Show the invite link used in inactivity DMs. | `app/plugins/commands_modular/inattivi.py:395` |
| `inactivity` | `dms` | `template_reminder_reset` | Reset the reminder DM template. | `app/plugins/commands_modular/inattivi.py:355` |
| `inactivity` | `dms` | `template_reminder_set` | Set the reminder DM template. | `app/plugins/commands_modular/inattivi.py:334` |
| `inactivity` | `dms` | `template_reminder_show` | Show the reminder DM template. | `app/plugins/commands_modular/inattivi.py:341` |
| `inactivity` | `grace` | `config_reset` | Reset the inactivity grace period configuration. | `app/plugins/commands_modular/inattivi.py:279` |
| `inactivity` | `grace` | `config_set` | Set the inactivity grace period configuration. | `app/plugins/commands_modular/inattivi.py:264` |
| `inactivity` | `grace` | `config_show` | Show the inactivity grace period configuration. | `app/plugins/commands_modular/inattivi.py:271` |
| `inactivity` | `grace` | `off` | Disable the inactivity grace period. | `app/plugins/commands_modular/inattivi.py:248` |
| `inactivity` | `grace` | `on` | Enable the inactivity grace period. | `app/plugins/commands_modular/inattivi.py:239` |
| `inactivity` | `grace` | `status` | Show the inactivity grace period status. | `app/plugins/commands_modular/inattivi.py:255` |
| `inactivity` | `—` | `off` | Disable inactivity moderation. | `app/plugins/commands_modular/inattivi.py:179` |
| `inactivity` | `—` | `on` | Enable inactivity moderation. | `app/plugins/commands_modular/inattivi.py:172` |
| `inactivity` | `policy` | `default_reset` | Reset the default inactivity policy. | `app/plugins/commands_modular/inattivi.py:443` |
| `inactivity` | `policy` | `default_set` | Set the default inactivity policy. | `app/plugins/commands_modular/inattivi.py:416` |
| `inactivity` | `policy` | `default_show` | Show the default inactivity policy. | `app/plugins/commands_modular/inattivi.py:435` |
| `inactivity` | `policy` | `exceptions_add` | Add a role to the inactivity exception list. | `app/plugins/commands_modular/inattivi.py:502` |
| `inactivity` | `policy` | `exceptions_list` | List all inactivity exception roles. | `app/plugins/commands_modular/inattivi.py:539` |
| `inactivity` | `policy` | `exceptions_remove` | Remove a role from the inactivity exception list. | `app/plugins/commands_modular/inattivi.py:516` |
| `inactivity` | `policy` | `exceptions_show` | Show whether a role is excluded from inactivity moderation. | `app/plugins/commands_modular/inattivi.py:530` |
| `inactivity` | `policy` | `role_reset` | Reset an inactivity policy for a role. | `app/plugins/commands_modular/inattivi.py:494` |
| `inactivity` | `policy` | `role_set` | Set an inactivity policy for a role. | `app/plugins/commands_modular/inattivi.py:459` |
| `inactivity` | `policy` | `role_show` | Show an inactivity policy for a role. | `app/plugins/commands_modular/inattivi.py:481` |
| `inactivity` | `—` | `run` | Run the inactivity moderation scan now. | `app/plugins/commands_modular/inattivi.py:554` |
| `inactivity` | `—` | `status` | Show the inactivity moderation status. | `app/plugins/commands_modular/inattivi.py:186` |
| `inactivity` | `tempban` | `config_reset` | Reset the inactivity tempban configuration. | `app/plugins/commands_modular/inattivi.py:326` |
| `inactivity` | `tempban` | `config_set` | Set the inactivity tempban configuration. | `app/plugins/commands_modular/inattivi.py:311` |
| `inactivity` | `tempban` | `config_show` | Show the inactivity tempban configuration. | `app/plugins/commands_modular/inattivi.py:318` |
| `inactivity` | `tempban` | `off` | Disable temporary bans after inactivity kicks. | `app/plugins/commands_modular/inattivi.py:295` |
| `inactivity` | `tempban` | `on` | Enable temporary bans after inactivity kicks. | `app/plugins/commands_modular/inattivi.py:286` |
| `inactivity` | `tempban` | `status` | Show the inactivity tempban status. | `app/plugins/commands_modular/inattivi.py:302` |
| `insights` | `—` | `off` | Disable insights in the current channel | `app/plugins/commands_modular/triggers.py:933` |
| `insights` | `—` | `on` | Enable insights in the current channel | `app/plugins/commands_modular/triggers.py:929` |
| `insights` | `—` | `status` | Show insights status for the current channel | `app/plugins/commands_modular/triggers.py:937` |
| `insights` | `—` | `template_reset` | Reset the insights template to defaults | `app/plugins/commands_modular/triggers.py:973` |
| `insights` | `—` | `template_set` | Set the insights template | `app/plugins/commands_modular/triggers.py:951` |
| `insights` | `—` | `template_show` | Show the insights template | `app/plugins/commands_modular/triggers.py:961` |
| `mod` | `channel` | `notify_reset` | Reset the moderation notification channel. | `app/plugins/commands_modular/moderazione_utenti.py:152` |
| `mod` | `channel` | `notify_set` | Set the moderation notification channel. | `app/plugins/commands_modular/moderazione_utenti.py:137` |
| `mod` | `channel` | `notify_show` | Show the moderation notification channel. | `app/plugins/commands_modular/moderazione_utenti.py:144` |
| `mod` | `channel` | `off` | Disable moderation notifications for the channel setting. | `app/plugins/commands_modular/moderazione_utenti.py:123` |
| `mod` | `channel` | `on` | Enable moderation notifications for a channel. | `app/plugins/commands_modular/moderazione_utenti.py:110` |
| `mod` | `channel` | `status` | Show the moderation channel configuration status. | `app/plugins/commands_modular/moderazione_utenti.py:130` |
| `mod` | `channel` | `template_reset` | Reset a moderation notification template. | `app/plugins/commands_modular/moderazione_utenti.py:194` |
| `mod` | `channel` | `template_set` | Set a moderation notification template. | `app/plugins/commands_modular/moderazione_utenti.py:160` |
| `mod` | `channel` | `template_show` | Show moderation notification templates. | `app/plugins/commands_modular/moderazione_utenti.py:172` |
| `mod` | `channel` | `user_card_reset` | Reset the moderation notification user card setting. | `app/plugins/commands_modular/moderazione_utenti.py:221` |
| `mod` | `channel` | `user_card_set` | Set whether moderation notifications include the user card. | `app/plugins/commands_modular/moderazione_utenti.py:206` |
| `mod` | `channel` | `user_card_show` | Show whether the moderation notification user card is enabled. | `app/plugins/commands_modular/moderazione_utenti.py:213` |
| `mod` | `users` | `ban` | Ban a user permanently. | `app/plugins/commands_modular/moderazione_utenti.py:288` |
| `mod` | `users` | `ban_list` | List active permanent bans. | `app/plugins/commands_modular/moderazione_utenti.py:304` |
| `mod` | `users` | `grace` | Assign a manual grace period to a user. | `app/plugins/commands_modular/moderazione_utenti.py:354` |
| `mod` | `users` | `grace_list` | List active grace periods. | `app/plugins/commands_modular/moderazione_utenti.py:385` |
| `mod` | `users` | `kick` | Kick a user. | `app/plugins/commands_modular/moderazione_utenti.py:263` |
| `mod` | `users` | `kick_list` | List recent kicks. | `app/plugins/commands_modular/moderazione_utenti.py:279` |
| `mod` | `users` | `tempban` | Ban a user temporarily. | `app/plugins/commands_modular/moderazione_utenti.py:313` |
| `mod` | `users` | `tempban_list` | List active temporary bans. | `app/plugins/commands_modular/moderazione_utenti.py:345` |
| `privacy` | `—` | `off` | Disable voice privacy. | `app/plugins/commands_modular/privacy.py:92` |
| `privacy` | `—` | `on` | Enable voice privacy. | `app/plugins/commands_modular/privacy.py:70` |
| `privacy` | `—` | `status` | Show the current voice privacy status. | `app/plugins/commands_modular/privacy.py:115` |
| `qna` | `—` | `bonus_reset` | Reset a user's QnA bonus | `app/plugins/commands_modular/triggers.py:919` |
| `qna` | `—` | `bonus_set` | Set a QnA bonus for a user | `app/plugins/commands_modular/triggers.py:888` |
| `qna` | `—` | `bonus_show` | Show a user's QnA bonus | `app/plugins/commands_modular/triggers.py:908` |
| `qna` | `—` | `limits_reset` | Reset QnA daily limits to defaults | `app/plugins/commands_modular/triggers.py:878` |
| `qna` | `—` | `limits_set` | Set a QnA daily limit | `app/plugins/commands_modular/triggers.py:857` |
| `qna` | `—` | `limits_show` | Show QnA daily limits | `app/plugins/commands_modular/triggers.py:833` |
| `qna` | `—` | `off` | Disable QnA in the current channel | `app/plugins/commands_modular/triggers.py:823` |
| `qna` | `—` | `on` | Enable QnA in the current channel | `app/plugins/commands_modular/triggers.py:819` |
| `qna` | `—` | `status` | Show QnA status for the current channel | `app/plugins/commands_modular/triggers.py:827` |
| `resocontocanale` | `—` | `ieri` | Show manual channel aura details for yesterday. | `app/plugins/commands_modular/resoconto.py:610` |
| `resocontocanale` | `—` | `off` | Disable automatic channel summaries for the current channel. | `app/plugins/commands_modular/resoconto.py:400` |
| `resocontocanale` | `—` | `oggi` | Show manual channel aura details for today. | `app/plugins/commands_modular/resoconto.py:606` |
| `resocontocanale` | `—` | `on` | Enable automatic channel summaries for the current channel. | `app/plugins/commands_modular/resoconto.py:384` |
| `resocontocanale` | `—` | `range` | Show manual channel aura details for a range. | `app/plugins/commands_modular/resoconto.py:630` |
| `resocontocanale` | `—` | `schedule_add` | Add a channel summary schedule. | `app/plugins/commands_modular/resoconto.py:459` |
| `resocontocanale` | `—` | `schedule_edit` | Edit a channel summary schedule. | `app/plugins/commands_modular/resoconto.py:487` |
| `resocontocanale` | `—` | `schedule_list` | List channel summary schedules for the current channel. | `app/plugins/commands_modular/resoconto.py:588` |
| `resocontocanale` | `—` | `schedule_remove` | Remove a channel summary schedule. | `app/plugins/commands_modular/resoconto.py:541` |
| `resocontocanale` | `—` | `schedule_show` | Show one channel summary schedule. | `app/plugins/commands_modular/resoconto.py:565` |
| `resocontocanale` | `—` | `status` | Show the channel summary schedule status. | `app/plugins/commands_modular/resoconto.py:416` |
| `resocontocanale` | `—` | `ultimi` | Show manual channel aura details for the last window. | `app/plugins/commands_modular/resoconto.py:622` |
| `resocontoserver` | `—` | `ieri` | Show manual server aura details for yesterday. | `app/plugins/commands_modular/resoconto.py:855` |
| `resocontoserver` | `—` | `off` | Disable automatic server summaries. | `app/plugins/commands_modular/resoconto.py:657` |
| `resocontoserver` | `—` | `oggi` | Show manual server aura details for today. | `app/plugins/commands_modular/resoconto.py:850` |
| `resocontoserver` | `—` | `on` | Enable automatic server summaries. | `app/plugins/commands_modular/resoconto.py:640` |
| `resocontoserver` | `—` | `range` | Show manual server aura details for a range. | `app/plugins/commands_modular/resoconto.py:876` |
| `resocontoserver` | `—` | `schedule_add` | Add a server summary schedule. | `app/plugins/commands_modular/resoconto.py:716` |
| `resocontoserver` | `—` | `schedule_edit` | Edit a server summary schedule. | `app/plugins/commands_modular/resoconto.py:744` |
| `resocontoserver` | `—` | `schedule_list` | List server summary schedules. | `app/plugins/commands_modular/resoconto.py:832` |
| `resocontoserver` | `—` | `schedule_remove` | Remove a server summary schedule. | `app/plugins/commands_modular/resoconto.py:793` |
| `resocontoserver` | `—` | `schedule_show` | Show one server summary schedule. | `app/plugins/commands_modular/resoconto.py:813` |
| `resocontoserver` | `—` | `status` | Show the server summary schedule status. | `app/plugins/commands_modular/resoconto.py:673` |
| `resocontoserver` | `—` | `ultimi` | Show manual server aura details for the last window. | `app/plugins/commands_modular/resoconto.py:868` |
| `riassunto` | `—` | `ieri` | Riassunto della giornata di ieri | `app/plugins/commands_modular/riassunto.py:1906` |
| `riassunto` | `—` | `oggi` | Riassunto della giornata di oggi | `app/plugins/commands_modular/riassunto.py:1901` |
| `riassunto` | `—` | `range` | Riassunto per intervallo | `app/plugins/commands_modular/riassunto.py:1912` |
| `riassunto` | `—` | `ultimi` | Riassunto ultimi N periodi | `app/plugins/commands_modular/riassunto.py:1882` |
| `stt` | `—` | `config_reset` | Reset the STT configuration to defaults. | `app/plugins/commands_modular/stt.py:127` |
| `stt` | `—` | `config_set` | Update the STT configuration. | `app/plugins/commands_modular/stt.py:62` |
| `stt` | `—` | `config_show` | Show the STT configuration. | `app/plugins/commands_modular/stt.py:110` |
| `translate` | `—` | `config_reset` | Reset the translation configuration to defaults. | `app/plugins/commands_modular/translate.py:86` |
| `translate` | `—` | `config_set` | Update the translation configuration. | `app/plugins/commands_modular/translate.py:32` |
| `translate` | `—` | `config_show` | Show the translation configuration. | `app/plugins/commands_modular/translate.py:69` |
| `voice_ingest` | `—` | `join` | Join a voice channel manually. | `app/plugins/commands_modular/voice_ingest.py:20` |
| `voice_ingest` | `—` | `leave` | Leave the current voice channel manually. | `app/plugins/commands_modular/voice_ingest.py:46` |

## Issues

- **WARNING missing_param_description** — `aura.ieri`: Parameter 'utente' is missing a description. (`app/plugins/commands_modular/aura.py:457`)
- **WARNING missing_param_description** — `aura.oggi`: Parameter 'utente' is missing a description. (`app/plugins/commands_modular/aura.py:452`)
- **WARNING missing_param_description** — `inactivity.dms.template_reminder_set`: Parameter 'text' is missing a description. (`app/plugins/commands_modular/inattivi.py:334`)
- **WARNING missing_param_description** — `mod.channel.template_set`: Parameter 'text' is missing a description. (`app/plugins/commands_modular/moderazione_utenti.py:160`)
- **WARNING missing_param_description** — `resocontocanale.range`: Parameter 'da' is missing a description. (`app/plugins/commands_modular/resoconto.py:630`)
- **WARNING missing_param_description** — `resocontocanale.range`: Parameter 'a' is missing a description. (`app/plugins/commands_modular/resoconto.py:630`)
- **WARNING missing_param_description** — `resocontocanale.ultimi`: Parameter 'quantita' is missing a description. (`app/plugins/commands_modular/resoconto.py:622`)
- **WARNING missing_param_description** — `resocontocanale.ultimi`: Parameter 'unita' is missing a description. (`app/plugins/commands_modular/resoconto.py:622`)
- **WARNING missing_param_description** — `resocontoserver.range`: Parameter 'da' is missing a description. (`app/plugins/commands_modular/resoconto.py:876`)
- **WARNING missing_param_description** — `resocontoserver.range`: Parameter 'a' is missing a description. (`app/plugins/commands_modular/resoconto.py:876`)
- **WARNING missing_param_description** — `resocontoserver.ultimi`: Parameter 'quantita' is missing a description. (`app/plugins/commands_modular/resoconto.py:868`)
- **WARNING missing_param_description** — `resocontoserver.ultimi`: Parameter 'unita' is missing a description. (`app/plugins/commands_modular/resoconto.py:868`)
- **WARNING required_param** — `bm.ai.fallback_set`: Parameter 'model' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/admin.py:609`)
- **WARNING required_param** — `bm.ai.model_set`: Parameter 'model' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/admin.py:564`)
- **WARNING required_param** — `bm.barcello.mood_set`: Parameter 'value' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/barcello.py:180`)
- **WARNING required_param** — `bm.footer.template_service_set`: Parameter 'phrase' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/admin.py:802`)
- **WARNING required_param** — `campagne.cap.config_set`: Parameter 'daily_limit' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/messaggi.py:520`)
- **WARNING required_param** — `campagne.quiet.config_set`: Parameter 'start' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/messaggi.py:473`)
- **WARNING required_param** — `campagne.quiet.config_set`: Parameter 'end' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/messaggi.py:473`)
- **WARNING required_param** — `frasi.template_global_set`: Parameter 'text' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:474`)
- **WARNING required_param** — `frasi.template_milestone_set`: Parameter 'threshold' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:431`)
- **WARNING required_param** — `frasi.template_milestone_set`: Parameter 'text' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:431`)
- **WARNING required_param** — `frasi.template_user_set`: Parameter 'text' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:519`)
- **WARNING required_param** — `inactivity.dms.cooldown_set`: Parameter 'days' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:363`)
- **WARNING required_param** — `inactivity.dms.invite_set`: Parameter 'url' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:388`)
- **WARNING required_param** — `inactivity.dms.template_reminder_set`: Parameter 'text' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:334`)
- **WARNING required_param** — `inactivity.grace.config_set`: Parameter 'days' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:264`)
- **WARNING required_param** — `inactivity.policy.default_set`: Parameter 'inactive_days' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:418`)
- **WARNING required_param** — `inactivity.policy.default_set`: Parameter 'window_days' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:419`)
- **WARNING required_param** — `inactivity.policy.default_set`: Parameter 'min_messages' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:420`)
- **WARNING required_param** — `inactivity.policy.default_set`: Parameter 'mode' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:421`)
- **WARNING required_param** — `inactivity.policy.role_set`: Parameter 'inactive_days' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:462`)
- **WARNING required_param** — `inactivity.policy.role_set`: Parameter 'window_days' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:463`)
- **WARNING required_param** — `inactivity.policy.role_set`: Parameter 'min_messages' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:464`)
- **WARNING required_param** — `inactivity.policy.role_set`: Parameter 'mode' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:465`)
- **WARNING required_param** — `inactivity.tempban.config_set`: Parameter 'days' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:311`)
- **WARNING required_param** — `insights.template_set`: Parameter 'text' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:951`)
- **WARNING required_param** — `mod.channel.template_set`: Parameter 'text' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/moderazione_utenti.py:160`)
- **WARNING required_param** — `mod.channel.user_card_set`: Parameter 'enabled' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/moderazione_utenti.py:206`)
- **WARNING required_param** — `qna.bonus_set`: Parameter 'amount' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:888`)
- **WARNING required_param** — `qna.limits_set`: Parameter 'tier' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:857`)
- **WARNING required_param** — `qna.limits_set`: Parameter 'limit' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:857`)

## Compatibility alias review

- **INFO compatibility_alias** — `app/plugins/commands_modular/roles.py`: `if not await check_permission(interaction, "bm.commandguard.role_add", ctx, legacy_aliases=["bm.role.set_role"]):` (`app/plugins/commands_modular/roles.py:49`)
- **INFO compatibility_alias** — `app/plugins/commands_modular/roles.py`: `if not await check_permission(interaction, "bm.commandguard.role_edit", ctx, legacy_aliases=["bm.role.set_role"]):` (`app/plugins/commands_modular/roles.py:59`)
- **INFO compatibility_alias** — `app/plugins/commands_modular/roles.py`: `if not await check_permission(interaction, "bm.commandguard.user_add", ctx, legacy_aliases=["bm.role.set_user"]):` (`app/plugins/commands_modular/roles.py:108`)
- **INFO compatibility_alias** — `app/plugins/commands_modular/roles.py`: `if not await check_permission(interaction, "bm.commandguard.user_edit", ctx, legacy_aliases=["bm.role.set_user"]):` (`app/plugins/commands_modular/roles.py:118`)
- **INFO compatibility_alias** — `app/plugins/commands_modular/triggers.py`: `scope = await _require_channel(interaction, "frasi.add")` (`app/plugins/commands_modular/triggers.py:257`)
- **INFO compatibility_alias** — `app/plugins/commands_modular/triggers.py`: `scope = await _require_channel(interaction, "frasi.remove")` (`app/plugins/commands_modular/triggers.py:292`)
- **INFO compatibility_alias** — `app/plugins/commands_modular/triggers.py`: `scope = await _require_channel(interaction, "frasi.list")` (`app/plugins/commands_modular/triggers.py:305`)
- **INFO compatibility_alias** — `app/plugins/commands_modular/triggers.py`: `scope = await _require_channel(interaction, "frasi.milestone_global_set")` (`app/plugins/commands_modular/triggers.py:432`)
- **INFO compatibility_alias** — `app/plugins/commands_modular/triggers.py`: `scope = await _require_channel(interaction, "frasi.milestone_global_list", "frasi.milestone_global_status")` (`app/plugins/commands_modular/triggers.py:449`)
- **INFO compatibility_alias** — `app/plugins/commands_modular/triggers.py`: `scope = await _require_channel(interaction, "frasi.milestone_global_remove")` (`app/plugins/commands_modular/triggers.py:462`)
- **INFO compatibility_alias** — `app/plugins/commands_modular/triggers.py`: `scope = await _require_channel(interaction, "frasi.template_set")` (`app/plugins/commands_modular/triggers.py:475`)
- **INFO compatibility_alias** — `app/plugins/commands_modular/triggers.py`: `scope = await _require_channel(interaction, "frasi.template_show")` (`app/plugins/commands_modular/triggers.py:489`)
- **INFO compatibility_alias** — `app/plugins/commands_modular/triggers.py`: `scope = await _require_channel(interaction, "frasi.template_reset")` (`app/plugins/commands_modular/triggers.py:502`)
- **INFO compatibility_alias** — `app/plugins/commands_modular/triggers.py`: `scope = await _require_channel(interaction, "frasi.userphrase_set")` (`app/plugins/commands_modular/triggers.py:520`)
- **INFO compatibility_alias** — `app/plugins/commands_modular/triggers.py`: `scope = await _require_channel(interaction, "frasi.userphrase_show")` (`app/plugins/commands_modular/triggers.py:537`)
- **INFO compatibility_alias** — `app/plugins/commands_modular/triggers.py`: `scope = await _require_channel(interaction, "frasi.userphrase_remove")` (`app/plugins/commands_modular/triggers.py:550`)

## Localized exceptions

The following commands remain intentionally localized and are excluded from the English-only rule for now:
- `attivita.ieri`
- `attivita.oggi`
- `attivita.range`
- `attivita.ultimi`
- `aura.ieri`
- `aura.oggi`
- `aura.range`
- `aura.ultimi`
- `domanda`
- `frasi.entry_add`
- `frasi.entry_edit`
- `frasi.entry_list`
- `frasi.entry_remove`
- `frasi.entry_show`
- `frasi.off`
- `frasi.on`
- `frasi.status`
- `frasi.template_global_reset`
- `frasi.template_global_set`
- `frasi.template_global_show`
- `frasi.template_milestone_reset`
- `frasi.template_milestone_set`
- `frasi.template_milestone_show`
- `frasi.template_user_reset`
- `frasi.template_user_set`
- `frasi.template_user_show`
- `resocontocanale.ieri`
- `resocontocanale.off`
- `resocontocanale.oggi`
- `resocontocanale.on`
- `resocontocanale.range`
- `resocontocanale.schedule_add`
- `resocontocanale.schedule_edit`
- `resocontocanale.schedule_list`
- `resocontocanale.schedule_remove`
- `resocontocanale.schedule_show`
- `resocontocanale.status`
- `resocontocanale.ultimi`
- `resocontoserver.ieri`
- `resocontoserver.off`
- `resocontoserver.oggi`
- `resocontoserver.on`
- `resocontoserver.range`
- `resocontoserver.schedule_add`
- `resocontoserver.schedule_edit`
- `resocontoserver.schedule_list`
- `resocontoserver.schedule_remove`
- `resocontoserver.schedule_show`
- `resocontoserver.status`
- `resocontoserver.ultimi`
- `riassunto.ieri`
- `riassunto.oggi`
- `riassunto.range`
- `riassunto.ultimi`

## Usage

- Run `python -m scripts.validate_commands` for a console report.
- Run `python -m scripts.validate_commands --write-report` to refresh this markdown file.
- Run `pytest tests/test_command_standard_validator.py` to fail CI on validator errors.
