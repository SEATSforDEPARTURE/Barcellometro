# Command Tree Validation Report

- Commands discovered: **266**
- Errors: **0**
- Warnings: **51**

## Inventory

| Root | Subgroup | Action | Description | Source |
| --- | --- | --- | --- | --- |
| `admin` | `ai` | `fallback_set` | Set the AI fallback model for a task. | `app/plugins/commands_modular/admin.py:611` |
| `admin` | `ai` | `fallback_show` | Show configured AI fallback models. | `app/plugins/commands_modular/admin.py:642` |
| `admin` | `ai` | `model_set` | Set the AI model for a task. | `app/plugins/commands_modular/admin.py:566` |
| `admin` | `ai` | `model_show` | Show configured AI models. | `app/plugins/commands_modular/admin.py:597` |
| `admin` | `ai` | `off` | Disable the AI service. | `app/plugins/commands_modular/admin.py:556` |
| `admin` | `ai` | `on` | Enable the AI service. | `app/plugins/commands_modular/admin.py:549` |
| `admin` | `ai` | `run` | Run an AI test prompt. | `app/plugins/commands_modular/admin.py:688` |
| `admin` | `ai` | `status` | Show AI service status. | `app/plugins/commands_modular/admin.py:653` |
| `admin` | `backfill` | `config_reset` | Reset backfill configuration to defaults. | `app/plugins/commands_modular/admin.py:508` |
| `admin` | `backfill` | `config_set` | Update backfill configuration. | `app/plugins/commands_modular/admin.py:461` |
| `admin` | `backfill` | `config_show` | Show backfill configuration. | `app/plugins/commands_modular/admin.py:496` |
| `admin` | `backfill` | `off` | Disable backfill. | `app/plugins/commands_modular/admin.py:439` |
| `admin` | `backfill` | `on` | Enable backfill. | `app/plugins/commands_modular/admin.py:432` |
| `admin` | `backfill` | `run` | Run backfill now. | `app/plugins/commands_modular/admin.py:523` |
| `admin` | `backfill` | `status` | Show backfill status. | `app/plugins/commands_modular/admin.py:446` |
| `admin` | `barcello` | `calibrate` | Recalculate Barcello calibration weights. | `app/plugins/commands_modular/barcello.py:224` |
| `admin` | `barcello` | `mood_reset` | Reset the Barcello mood for this channel. | `app/plugins/commands_modular/barcello.py:213` |
| `admin` | `barcello` | `mood_set` | Set the Barcello mood for this channel. | `app/plugins/commands_modular/barcello.py:180` |
| `admin` | `barcello` | `mood_show` | Show the Barcello mood for this channel. | `app/plugins/commands_modular/barcello.py:209` |
| `admin` | `barcello` | `off` | Disable the Barcello trigger for this channel. | `app/plugins/commands_modular/barcello.py:171` |
| `admin` | `barcello` | `on` | Enable the Barcello trigger for this channel. | `app/plugins/commands_modular/barcello.py:167` |
| `admin` | `barcello` | `run` | Run the Barcello analysis. | `app/plugins/commands_modular/barcello.py:1095` |
| `admin` | `barcello` | `status` | Show Barcello trigger status for this channel. | `app/plugins/commands_modular/barcello.py:175` |
| `admin` | `events` | `off` | Disable event collection for this channel. | `app/plugins/commands_modular/admin.py:329` |
| `admin` | `events` | `on` | Enable event collection for this channel. | `app/plugins/commands_modular/admin.py:323` |
| `admin` | `events` | `status` | Show event collection status for this channel. | `app/plugins/commands_modular/admin.py:335` |
| `admin` | `footer` | `off` | Disable footer rendering. | `app/plugins/commands_modular/admin.py:729` |
| `admin` | `footer` | `on` | Enable footer rendering. | `app/plugins/commands_modular/admin.py:719` |
| `admin` | `footer` | `status` | Show footer status and rendered variants. | `app/plugins/commands_modular/admin.py:858` |
| `admin` | `footer` | `template_global_reset` | Reset the global footer template. | `app/plugins/commands_modular/admin.py:792` |
| `admin` | `footer` | `template_global_set` | Set the global footer template. | `app/plugins/commands_modular/admin.py:740` |
| `admin` | `footer` | `template_global_show` | Show the global footer template. | `app/plugins/commands_modular/admin.py:775` |
| `admin` | `footer` | `template_service_reset` | Reset a service-specific footer template. | `app/plugins/commands_modular/admin.py:844` |
| `admin` | `footer` | `template_service_set` | Set a service-specific footer template. | `app/plugins/commands_modular/admin.py:804` |
| `admin` | `footer` | `template_service_show` | Show a service-specific footer template. | `app/plugins/commands_modular/admin.py:823` |
| `admin` | `retention` | `config_reset` | Reset retention configuration to defaults. | `app/plugins/commands_modular/admin.py:417` |
| `admin` | `retention` | `config_set` | Update retention configuration. | `app/plugins/commands_modular/admin.py:370` |
| `admin` | `retention` | `config_show` | Show retention configuration. | `app/plugins/commands_modular/admin.py:405` |
| `admin` | `retention` | `off` | Disable the retention task. | `app/plugins/commands_modular/admin.py:348` |
| `admin` | `retention` | `on` | Enable the retention task. | `app/plugins/commands_modular/admin.py:341` |
| `admin` | `retention` | `status` | Show retention status. | `app/plugins/commands_modular/admin.py:355` |
| `admin` | `—` | `status` | Show the Barcellometro status. | `app/plugins/commands_modular/status.py:14` |
| `attivita` | `—` | `ieri` | Report attività di ieri (DM staff) | `app/plugins/commands_modular/attivita.py:600` |
| `attivita` | `—` | `oggi` | Report attività di oggi (DM staff) | `app/plugins/commands_modular/attivita.py:595` |
| `attivita` | `—` | `range` | Report attività per range custom | `app/plugins/commands_modular/attivita.py:625` |
| `attivita` | `—` | `ultimi` | Report attività ultimi N periodi | `app/plugins/commands_modular/attivita.py:613` |
| `audionotes` | `—` | `config_reset` | Reset the audio notes configuration to defaults. | `app/plugins/commands_modular/audio_notes.py:167` |
| `audionotes` | `—` | `config_set` | Update the audio notes configuration. | `app/plugins/commands_modular/audio_notes.py:82` |
| `audionotes` | `—` | `config_show` | Show the audio notes configuration. | `app/plugins/commands_modular/audio_notes.py:148` |
| `audionotes` | `—` | `off` | Disable audio notes. | `app/plugins/commands_modular/audio_notes.py:40` |
| `audionotes` | `—` | `on` | Enable audio notes. | `app/plugins/commands_modular/audio_notes.py:26` |
| `audionotes` | `—` | `status` | Show the audio notes status. | `app/plugins/commands_modular/audio_notes.py:54` |
| `aura` | `—` | `ieri` | Aura di ieri | `app/plugins/commands_modular/aura.py:457` |
| `aura` | `—` | `oggi` | Aura di oggi | `app/plugins/commands_modular/aura.py:452` |
| `aura` | `—` | `range` | Aura per intervallo | `app/plugins/commands_modular/aura.py:463` |
| `aura` | `—` | `ultimi` | Aura ultimi N periodi | `app/plugins/commands_modular/aura.py:435` |
| `campagne` | `cap` | `config_reset` | Reset the daily cap configuration | `app/plugins/commands_modular/messaggi.py:598` |
| `campagne` | `cap` | `config_set` | Set the daily cap configuration | `app/plugins/commands_modular/messaggi.py:581` |
| `campagne` | `cap` | `config_show` | Show the daily cap configuration | `app/plugins/commands_modular/messaggi.py:591` |
| `campagne` | `cap` | `off` | Disable the daily cap | `app/plugins/commands_modular/messaggi.py:565` |
| `campagne` | `cap` | `on` | Enable the daily cap | `app/plugins/commands_modular/messaggi.py:558` |
| `campagne` | `cap` | `status` | Show the daily cap status | `app/plugins/commands_modular/messaggi.py:572` |
| `campagne` | `custom` | `off` | Disable custom campaigns in the current channel | `app/plugins/commands_modular/messaggi.py:609` |
| `campagne` | `custom` | `on` | Enable custom campaigns in the current channel | `app/plugins/commands_modular/messaggi.py:605` |
| `campagne` | `custom` | `run` | Run a custom campaign schedule now | `app/plugins/commands_modular/messaggi.py:745` |
| `campagne` | `custom` | `schedule_add` | Add a custom campaign schedule | `app/plugins/commands_modular/messaggi.py:632` |
| `campagne` | `custom` | `schedule_edit` | Edit a custom campaign schedule | `app/plugins/commands_modular/messaggi.py:786` |
| `campagne` | `custom` | `schedule_list` | List custom campaign schedules | `app/plugins/commands_modular/messaggi.py:702` |
| `campagne` | `custom` | `schedule_remove` | Remove a custom campaign schedule | `app/plugins/commands_modular/messaggi.py:730` |
| `campagne` | `custom` | `schedule_show` | Show a custom campaign schedule | `app/plugins/commands_modular/messaggi.py:716` |
| `campagne` | `custom` | `status` | Show custom campaign status for the current channel | `app/plugins/commands_modular/messaggi.py:613` |
| `campagne` | `horoscope` | `off` | Disable horoscope campaigns in the current channel | `app/plugins/commands_modular/messaggi.py:1075` |
| `campagne` | `horoscope` | `on` | Enable horoscope campaigns in the current channel | `app/plugins/commands_modular/messaggi.py:1071` |
| `campagne` | `horoscope` | `run` | Run the horoscope campaign immediately | `app/plugins/commands_modular/messaggi.py:1156` |
| `campagne` | `horoscope` | `schedule_add` | Add a horoscope campaign schedule | `app/plugins/commands_modular/messaggi.py:1090` |
| `campagne` | `horoscope` | `schedule_edit` | Edit a horoscope campaign schedule | `app/plugins/commands_modular/messaggi.py:1119` |
| `campagne` | `horoscope` | `schedule_list` | List horoscope campaign schedules | `app/plugins/commands_modular/messaggi.py:1152` |
| `campagne` | `horoscope` | `schedule_remove` | Remove a horoscope campaign schedule | `app/plugins/commands_modular/messaggi.py:1148` |
| `campagne` | `horoscope` | `schedule_show` | Show a horoscope campaign schedule | `app/plugins/commands_modular/messaggi.py:1143` |
| `campagne` | `horoscope` | `status` | Show horoscope campaign status for the current channel | `app/plugins/commands_modular/messaggi.py:1079` |
| `campagne` | `news` | `off` | Disable news campaigns in the current channel | `app/plugins/commands_modular/messaggi.py:898` |
| `campagne` | `news` | `on` | Enable news campaigns in the current channel | `app/plugins/commands_modular/messaggi.py:894` |
| `campagne` | `news` | `run` | Run the news campaign immediately | `app/plugins/commands_modular/messaggi.py:978` |
| `campagne` | `news` | `schedule_add` | Add a news campaign schedule | `app/plugins/commands_modular/messaggi.py:914` |
| `campagne` | `news` | `schedule_edit` | Edit a news campaign schedule | `app/plugins/commands_modular/messaggi.py:943` |
| `campagne` | `news` | `schedule_list` | List news campaign schedules | `app/plugins/commands_modular/messaggi.py:974` |
| `campagne` | `news` | `schedule_remove` | Remove a news campaign schedule | `app/plugins/commands_modular/messaggi.py:970` |
| `campagne` | `news` | `schedule_show` | Show a news campaign schedule | `app/plugins/commands_modular/messaggi.py:965` |
| `campagne` | `news` | `status` | Show news campaign status for the current channel | `app/plugins/commands_modular/messaggi.py:902` |
| `campagne` | `—` | `off` | Disable campaigns in the current channel | `app/plugins/commands_modular/messaggi.py:486` |
| `campagne` | `—` | `on` | Enable campaigns in the current channel | `app/plugins/commands_modular/messaggi.py:475` |
| `campagne` | `prompt` | `off` | Disable prompt campaigns in the current channel | `app/plugins/commands_modular/triggers.py:622` |
| `campagne` | `prompt` | `on` | Enable prompt campaigns in the current channel | `app/plugins/commands_modular/triggers.py:610` |
| `campagne` | `prompt` | `run` | Run a prompt campaign schedule now | `app/plugins/commands_modular/triggers.py:755` |
| `campagne` | `prompt` | `schedule_add` | Add a prompt campaign schedule | `app/plugins/commands_modular/triggers.py:653` |
| `campagne` | `prompt` | `schedule_edit` | Edit a prompt campaign schedule | `app/plugins/commands_modular/triggers.py:799` |
| `campagne` | `prompt` | `schedule_list` | List prompt campaign schedules | `app/plugins/commands_modular/triggers.py:712` |
| `campagne` | `prompt` | `schedule_remove` | Remove a prompt campaign schedule | `app/plugins/commands_modular/triggers.py:740` |
| `campagne` | `prompt` | `schedule_show` | Show a prompt campaign schedule | `app/plugins/commands_modular/triggers.py:726` |
| `campagne` | `prompt` | `status` | Show prompt campaign status for the current channel | `app/plugins/commands_modular/triggers.py:634` |
| `campagne` | `quiet` | `config_reset` | Reset quiet hours configuration | `app/plugins/commands_modular/messaggi.py:550` |
| `campagne` | `quiet` | `config_set` | Set quiet hours configuration | `app/plugins/commands_modular/messaggi.py:534` |
| `campagne` | `quiet` | `config_show` | Show quiet hours configuration | `app/plugins/commands_modular/messaggi.py:542` |
| `campagne` | `quiet` | `off` | Disable quiet hours | `app/plugins/commands_modular/messaggi.py:517` |
| `campagne` | `quiet` | `on` | Enable quiet hours | `app/plugins/commands_modular/messaggi.py:510` |
| `campagne` | `quiet` | `status` | Show quiet hours status | `app/plugins/commands_modular/messaggi.py:524` |
| `campagne` | `—` | `status` | Show campaign status for the current channel | `app/plugins/commands_modular/messaggi.py:497` |
| `campagne` | `weather` | `off` | Disable weather campaigns in the current channel | `app/plugins/commands_modular/messaggi.py:986` |
| `campagne` | `weather` | `on` | Enable weather campaigns in the current channel | `app/plugins/commands_modular/messaggi.py:982` |
| `campagne` | `weather` | `run` | Run the weather campaign immediately | `app/plugins/commands_modular/messaggi.py:1067` |
| `campagne` | `weather` | `schedule_add` | Add a weather campaign schedule | `app/plugins/commands_modular/messaggi.py:1001` |
| `campagne` | `weather` | `schedule_edit` | Edit a weather campaign schedule | `app/plugins/commands_modular/messaggi.py:1030` |
| `campagne` | `weather` | `schedule_list` | List weather campaign schedules | `app/plugins/commands_modular/messaggi.py:1063` |
| `campagne` | `weather` | `schedule_remove` | Remove a weather campaign schedule | `app/plugins/commands_modular/messaggi.py:1059` |
| `campagne` | `weather` | `schedule_show` | Show a weather campaign schedule | `app/plugins/commands_modular/messaggi.py:1054` |
| `campagne` | `weather` | `status` | Show weather campaign status for the current channel | `app/plugins/commands_modular/messaggi.py:990` |
| `commandguard` | `—` | `role_add` | Add a role command policy. | `app/plugins/commands_modular/roles.py:56` |
| `commandguard` | `—` | `role_edit` | Edit a role command policy. | `app/plugins/commands_modular/roles.py:67` |
| `commandguard` | `—` | `role_list` | List all role policies. | `app/plugins/commands_modular/roles.py:98` |
| `commandguard` | `—` | `role_remove` | Remove a role command policy. | `app/plugins/commands_modular/roles.py:78` |
| `commandguard` | `—` | `role_reset` | Reset all policies for a role. | `app/plugins/commands_modular/roles.py:109` |
| `commandguard` | `—` | `role_show` | Show role policies. | `app/plugins/commands_modular/roles.py:86` |
| `commandguard` | `—` | `user_add` | Add a user command policy. | `app/plugins/commands_modular/roles.py:117` |
| `commandguard` | `—` | `user_edit` | Edit a user command policy. | `app/plugins/commands_modular/roles.py:128` |
| `commandguard` | `—` | `user_list` | List all user policies. | `app/plugins/commands_modular/roles.py:159` |
| `commandguard` | `—` | `user_remove` | Remove a user command policy. | `app/plugins/commands_modular/roles.py:139` |
| `commandguard` | `—` | `user_reset` | Reset all policies for a user. | `app/plugins/commands_modular/roles.py:170` |
| `commandguard` | `—` | `user_show` | Show user policies. | `app/plugins/commands_modular/roles.py:147` |
| `domanda` | `—` | `domanda` | Fai una domanda al Q&A | `app/plugins/commands_modular/ask.py:60` |
| `frasi` | `—` | `entry_add` | Add a phrase trigger entry | `app/plugins/commands_modular/triggers.py:299` |
| `frasi` | `—` | `entry_edit` | Edit a phrase trigger entry | `app/plugins/commands_modular/triggers.py:408` |
| `frasi` | `—` | `entry_list` | List phrase trigger entries | `app/plugins/commands_modular/triggers.py:354` |
| `frasi` | `—` | `entry_remove` | Remove a phrase trigger entry | `app/plugins/commands_modular/triggers.py:341` |
| `frasi` | `—` | `entry_show` | Show a phrase trigger entry | `app/plugins/commands_modular/triggers.py:367` |
| `frasi` | `—` | `off` | Disable phrase triggers | `app/plugins/commands_modular/triggers.py:283` |
| `frasi` | `—` | `on` | Enable phrase triggers | `app/plugins/commands_modular/triggers.py:279` |
| `frasi` | `—` | `status` | Show phrase trigger status | `app/plugins/commands_modular/triggers.py:287` |
| `frasi` | `—` | `template_global_reset` | Reset the global phrase template | `app/plugins/commands_modular/triggers.py:551` |
| `frasi` | `—` | `template_global_set` | Set the global phrase template | `app/plugins/commands_modular/triggers.py:524` |
| `frasi` | `—` | `template_global_show` | Show the global phrase template | `app/plugins/commands_modular/triggers.py:538` |
| `frasi` | `—` | `template_milestone_reset` | Reset all milestone templates | `app/plugins/commands_modular/triggers.py:511` |
| `frasi` | `—` | `template_milestone_set` | Create or update a milestone template | `app/plugins/commands_modular/triggers.py:481` |
| `frasi` | `—` | `template_milestone_show` | Show milestone templates | `app/plugins/commands_modular/triggers.py:498` |
| `frasi` | `—` | `template_user_reset` | Reset a user-specific phrase template | `app/plugins/commands_modular/triggers.py:599` |
| `frasi` | `—` | `template_user_set` | Set a user-specific phrase template | `app/plugins/commands_modular/triggers.py:569` |
| `frasi` | `—` | `template_user_show` | Show a user-specific phrase template | `app/plugins/commands_modular/triggers.py:586` |
| `inactivity` | `autokick` | `off` | Disable automatic inactivity actions. | `app/plugins/commands_modular/inattivi.py:224` |
| `inactivity` | `autokick` | `on` | Enable automatic inactivity actions. | `app/plugins/commands_modular/inattivi.py:217` |
| `inactivity` | `autokick` | `status` | Show the automatic inactivity action status. | `app/plugins/commands_modular/inattivi.py:231` |
| `inactivity` | `dms` | `cooldown_reset` | Reset the reminder DM cooldown. | `app/plugins/commands_modular/inattivi.py:376` |
| `inactivity` | `dms` | `cooldown_set` | Set the reminder DM cooldown. | `app/plugins/commands_modular/inattivi.py:362` |
| `inactivity` | `dms` | `cooldown_show` | Show the reminder DM cooldown. | `app/plugins/commands_modular/inattivi.py:369` |
| `inactivity` | `dms` | `invite_reset` | Reset the invite link used in inactivity DMs. | `app/plugins/commands_modular/inattivi.py:401` |
| `inactivity` | `dms` | `invite_set` | Set the invite link used in inactivity DMs. | `app/plugins/commands_modular/inattivi.py:387` |
| `inactivity` | `dms` | `invite_show` | Show the invite link used in inactivity DMs. | `app/plugins/commands_modular/inattivi.py:394` |
| `inactivity` | `dms` | `template_reminder_reset` | Reset the reminder DM template. | `app/plugins/commands_modular/inattivi.py:354` |
| `inactivity` | `dms` | `template_reminder_set` | Set the reminder DM template. | `app/plugins/commands_modular/inattivi.py:333` |
| `inactivity` | `dms` | `template_reminder_show` | Show the reminder DM template. | `app/plugins/commands_modular/inattivi.py:340` |
| `inactivity` | `grace` | `config_reset` | Reset the inactivity grace period configuration. | `app/plugins/commands_modular/inattivi.py:278` |
| `inactivity` | `grace` | `config_set` | Set the inactivity grace period configuration. | `app/plugins/commands_modular/inattivi.py:263` |
| `inactivity` | `grace` | `config_show` | Show the inactivity grace period configuration. | `app/plugins/commands_modular/inattivi.py:270` |
| `inactivity` | `grace` | `off` | Disable the inactivity grace period. | `app/plugins/commands_modular/inattivi.py:247` |
| `inactivity` | `grace` | `on` | Enable the inactivity grace period. | `app/plugins/commands_modular/inattivi.py:238` |
| `inactivity` | `grace` | `status` | Show the inactivity grace period status. | `app/plugins/commands_modular/inattivi.py:254` |
| `inactivity` | `—` | `off` | Disable inactivity moderation. | `app/plugins/commands_modular/inattivi.py:178` |
| `inactivity` | `—` | `on` | Enable inactivity moderation. | `app/plugins/commands_modular/inattivi.py:171` |
| `inactivity` | `policy` | `default_reset` | Reset the default inactivity policy. | `app/plugins/commands_modular/inattivi.py:442` |
| `inactivity` | `policy` | `default_set` | Set the default inactivity policy. | `app/plugins/commands_modular/inattivi.py:415` |
| `inactivity` | `policy` | `default_show` | Show the default inactivity policy. | `app/plugins/commands_modular/inattivi.py:434` |
| `inactivity` | `policy` | `exceptions_add` | Add a role to the inactivity exception list. | `app/plugins/commands_modular/inattivi.py:501` |
| `inactivity` | `policy` | `exceptions_list` | List all inactivity exception roles. | `app/plugins/commands_modular/inattivi.py:538` |
| `inactivity` | `policy` | `exceptions_remove` | Remove a role from the inactivity exception list. | `app/plugins/commands_modular/inattivi.py:515` |
| `inactivity` | `policy` | `exceptions_show` | Show whether a role is excluded from inactivity moderation. | `app/plugins/commands_modular/inattivi.py:529` |
| `inactivity` | `policy` | `role_reset` | Reset an inactivity policy for a role. | `app/plugins/commands_modular/inattivi.py:493` |
| `inactivity` | `policy` | `role_set` | Set an inactivity policy for a role. | `app/plugins/commands_modular/inattivi.py:458` |
| `inactivity` | `policy` | `role_show` | Show an inactivity policy for a role. | `app/plugins/commands_modular/inattivi.py:480` |
| `inactivity` | `—` | `run` | Run the inactivity moderation scan now. | `app/plugins/commands_modular/inattivi.py:553` |
| `inactivity` | `—` | `status` | Show the inactivity moderation status. | `app/plugins/commands_modular/inattivi.py:185` |
| `inactivity` | `tempban` | `config_reset` | Reset the inactivity tempban configuration. | `app/plugins/commands_modular/inattivi.py:325` |
| `inactivity` | `tempban` | `config_set` | Set the inactivity tempban configuration. | `app/plugins/commands_modular/inattivi.py:310` |
| `inactivity` | `tempban` | `config_show` | Show the inactivity tempban configuration. | `app/plugins/commands_modular/inattivi.py:317` |
| `inactivity` | `tempban` | `off` | Disable temporary bans after inactivity kicks. | `app/plugins/commands_modular/inattivi.py:294` |
| `inactivity` | `tempban` | `on` | Enable temporary bans after inactivity kicks. | `app/plugins/commands_modular/inattivi.py:285` |
| `inactivity` | `tempban` | `status` | Show the inactivity tempban status. | `app/plugins/commands_modular/inattivi.py:301` |
| `insights` | `—` | `off` | Disable insights in the current channel | `app/plugins/commands_modular/triggers.py:981` |
| `insights` | `—` | `on` | Enable insights in the current channel | `app/plugins/commands_modular/triggers.py:977` |
| `insights` | `—` | `status` | Show insights status for the current channel | `app/plugins/commands_modular/triggers.py:985` |
| `insights` | `—` | `template_reset` | Reset the insights template to defaults | `app/plugins/commands_modular/triggers.py:1021` |
| `insights` | `—` | `template_set` | Set the insights template | `app/plugins/commands_modular/triggers.py:999` |
| `insights` | `—` | `template_show` | Show the insights template | `app/plugins/commands_modular/triggers.py:1009` |
| `mod` | `channel` | `notify_reset` | Reset the moderation notification channel. | `app/plugins/commands_modular/moderazione_utenti.py:151` |
| `mod` | `channel` | `notify_set` | Set the moderation notification channel. | `app/plugins/commands_modular/moderazione_utenti.py:136` |
| `mod` | `channel` | `notify_show` | Show the moderation notification channel. | `app/plugins/commands_modular/moderazione_utenti.py:143` |
| `mod` | `channel` | `off` | Disable moderation notifications for the channel setting. | `app/plugins/commands_modular/moderazione_utenti.py:122` |
| `mod` | `channel` | `on` | Enable moderation notifications for a channel. | `app/plugins/commands_modular/moderazione_utenti.py:109` |
| `mod` | `channel` | `status` | Show the moderation channel configuration status. | `app/plugins/commands_modular/moderazione_utenti.py:129` |
| `mod` | `channel` | `template_reset` | Reset a moderation notification template. | `app/plugins/commands_modular/moderazione_utenti.py:193` |
| `mod` | `channel` | `template_set` | Set a moderation notification template. | `app/plugins/commands_modular/moderazione_utenti.py:159` |
| `mod` | `channel` | `template_show` | Show moderation notification templates. | `app/plugins/commands_modular/moderazione_utenti.py:171` |
| `mod` | `channel` | `user_card_reset` | Reset the moderation notification user card setting. | `app/plugins/commands_modular/moderazione_utenti.py:220` |
| `mod` | `channel` | `user_card_set` | Set whether moderation notifications include the user card. | `app/plugins/commands_modular/moderazione_utenti.py:205` |
| `mod` | `channel` | `user_card_show` | Show whether the moderation notification user card is enabled. | `app/plugins/commands_modular/moderazione_utenti.py:212` |
| `mod` | `users` | `ban` | Ban a user permanently. | `app/plugins/commands_modular/moderazione_utenti.py:287` |
| `mod` | `users` | `ban_list` | List active permanent bans. | `app/plugins/commands_modular/moderazione_utenti.py:303` |
| `mod` | `users` | `grace` | Assign a manual grace period to a user. | `app/plugins/commands_modular/moderazione_utenti.py:353` |
| `mod` | `users` | `grace_list` | List active grace periods. | `app/plugins/commands_modular/moderazione_utenti.py:384` |
| `mod` | `users` | `kick` | Kick a user. | `app/plugins/commands_modular/moderazione_utenti.py:262` |
| `mod` | `users` | `kick_list` | List recent kicks. | `app/plugins/commands_modular/moderazione_utenti.py:278` |
| `mod` | `users` | `tempban` | Ban a user temporarily. | `app/plugins/commands_modular/moderazione_utenti.py:312` |
| `mod` | `users` | `tempban_list` | List active temporary bans. | `app/plugins/commands_modular/moderazione_utenti.py:344` |
| `privacy` | `—` | `off` | Disable voice privacy. | `app/plugins/commands_modular/privacy.py:90` |
| `privacy` | `—` | `on` | Enable voice privacy. | `app/plugins/commands_modular/privacy.py:68` |
| `privacy` | `—` | `status` | Show the current voice privacy status. | `app/plugins/commands_modular/privacy.py:113` |
| `qna` | `—` | `bonus_reset` | Reset a user's QnA bonus | `app/plugins/commands_modular/triggers.py:967` |
| `qna` | `—` | `bonus_set` | Set a QnA bonus for a user | `app/plugins/commands_modular/triggers.py:936` |
| `qna` | `—` | `bonus_show` | Show a user's QnA bonus | `app/plugins/commands_modular/triggers.py:956` |
| `qna` | `—` | `limits_reset` | Reset QnA daily limits to defaults | `app/plugins/commands_modular/triggers.py:926` |
| `qna` | `—` | `limits_set` | Set a QnA daily limit | `app/plugins/commands_modular/triggers.py:905` |
| `qna` | `—` | `limits_show` | Show QnA daily limits | `app/plugins/commands_modular/triggers.py:881` |
| `qna` | `—` | `off` | Disable QnA in the current channel | `app/plugins/commands_modular/triggers.py:871` |
| `qna` | `—` | `on` | Enable QnA in the current channel | `app/plugins/commands_modular/triggers.py:867` |
| `qna` | `—` | `status` | Show QnA status for the current channel | `app/plugins/commands_modular/triggers.py:875` |
| `resocontocanale` | `aura` | `ieri` | Show manual channel aura details for yesterday. | `app/plugins/commands_modular/resoconto.py:622` |
| `resocontocanale` | `aura` | `oggi` | Show manual channel aura details for today. | `app/plugins/commands_modular/resoconto.py:614` |
| `resocontocanale` | `aura` | `range` | Show manual channel aura details for a range. | `app/plugins/commands_modular/resoconto.py:662` |
| `resocontocanale` | `aura` | `ultimi` | Show manual channel aura details for the last window. | `app/plugins/commands_modular/resoconto.py:650` |
| `resocontocanale` | `—` | `ieri` | Show manual channel aura details for yesterday. | `app/plugins/commands_modular/resoconto.py:618` |
| `resocontocanale` | `—` | `off` | Disable automatic channel summaries for the current channel. | `app/plugins/commands_modular/resoconto.py:400` |
| `resocontocanale` | `—` | `oggi` | Show manual channel aura details for today. | `app/plugins/commands_modular/resoconto.py:610` |
| `resocontocanale` | `—` | `on` | Enable automatic channel summaries for the current channel. | `app/plugins/commands_modular/resoconto.py:384` |
| `resocontocanale` | `—` | `range` | Show manual channel aura details for a range. | `app/plugins/commands_modular/resoconto.py:654` |
| `resocontocanale` | `—` | `schedule_add` | Add a channel summary schedule. | `app/plugins/commands_modular/resoconto.py:459` |
| `resocontocanale` | `—` | `schedule_edit` | Edit a channel summary schedule. | `app/plugins/commands_modular/resoconto.py:487` |
| `resocontocanale` | `—` | `schedule_list` | List channel summary schedules for the current channel. | `app/plugins/commands_modular/resoconto.py:588` |
| `resocontocanale` | `—` | `schedule_remove` | Remove a channel summary schedule. | `app/plugins/commands_modular/resoconto.py:541` |
| `resocontocanale` | `—` | `schedule_show` | Show one channel summary schedule. | `app/plugins/commands_modular/resoconto.py:565` |
| `resocontocanale` | `—` | `status` | Show the channel summary schedule status. | `app/plugins/commands_modular/resoconto.py:416` |
| `resocontocanale` | `—` | `ultimi` | Show manual channel aura details for the last window. | `app/plugins/commands_modular/resoconto.py:634` |
| `resocontoserver` | `aura` | `ieri` | Show manual server aura details for yesterday. | `app/plugins/commands_modular/resoconto.py:894` |
| `resocontoserver` | `aura` | `oggi` | Show manual server aura details for today. | `app/plugins/commands_modular/resoconto.py:885` |
| `resocontoserver` | `aura` | `range` | Show manual server aura details for a range. | `app/plugins/commands_modular/resoconto.py:934` |
| `resocontoserver` | `aura` | `ultimi` | Show manual server aura details for the last window. | `app/plugins/commands_modular/resoconto.py:922` |
| `resocontoserver` | `—` | `ieri` | Show manual server aura details for yesterday. | `app/plugins/commands_modular/resoconto.py:889` |
| `resocontoserver` | `—` | `off` | Disable automatic server summaries. | `app/plugins/commands_modular/resoconto.py:683` |
| `resocontoserver` | `—` | `oggi` | Show manual server aura details for today. | `app/plugins/commands_modular/resoconto.py:880` |
| `resocontoserver` | `—` | `on` | Enable automatic server summaries. | `app/plugins/commands_modular/resoconto.py:666` |
| `resocontoserver` | `—` | `range` | Show manual server aura details for a range. | `app/plugins/commands_modular/resoconto.py:926` |
| `resocontoserver` | `—` | `schedule_add` | Add a server summary schedule. | `app/plugins/commands_modular/resoconto.py:742` |
| `resocontoserver` | `—` | `schedule_edit` | Edit a server summary schedule. | `app/plugins/commands_modular/resoconto.py:770` |
| `resocontoserver` | `—` | `schedule_list` | List server summary schedules. | `app/plugins/commands_modular/resoconto.py:858` |
| `resocontoserver` | `—` | `schedule_remove` | Remove a server summary schedule. | `app/plugins/commands_modular/resoconto.py:819` |
| `resocontoserver` | `—` | `schedule_show` | Show one server summary schedule. | `app/plugins/commands_modular/resoconto.py:839` |
| `resocontoserver` | `—` | `status` | Show the server summary schedule status. | `app/plugins/commands_modular/resoconto.py:699` |
| `resocontoserver` | `—` | `ultimi` | Show manual server aura details for the last window. | `app/plugins/commands_modular/resoconto.py:906` |
| `riassunto` | `—` | `ieri` | Riassunto della giornata di ieri | `app/plugins/commands_modular/riassunto.py:1906` |
| `riassunto` | `—` | `oggi` | Riassunto della giornata di oggi | `app/plugins/commands_modular/riassunto.py:1901` |
| `riassunto` | `—` | `range` | Riassunto per intervallo | `app/plugins/commands_modular/riassunto.py:1912` |
| `riassunto` | `—` | `ultimi` | Riassunto ultimi N periodi | `app/plugins/commands_modular/riassunto.py:1882` |
| `stt` | `—` | `config_reset` | Reset the STT configuration to defaults. | `app/plugins/commands_modular/stt.py:125` |
| `stt` | `—` | `config_set` | Update the STT configuration. | `app/plugins/commands_modular/stt.py:62` |
| `stt` | `—` | `config_show` | Show the STT configuration. | `app/plugins/commands_modular/stt.py:109` |
| `translate` | `—` | `config_reset` | Reset the translation configuration to defaults. | `app/plugins/commands_modular/translate.py:84` |
| `translate` | `—` | `config_set` | Update the translation configuration. | `app/plugins/commands_modular/translate.py:32` |
| `translate` | `—` | `config_show` | Show the translation configuration. | `app/plugins/commands_modular/translate.py:68` |
| `voice_ingest` | `—` | `join` | Join a voice channel manually. | `app/plugins/commands_modular/voice_ingest.py:19` |
| `voice_ingest` | `—` | `leave` | Leave the current voice channel manually. | `app/plugins/commands_modular/voice_ingest.py:45` |

## Issues

- **WARNING missing_param_description** — `aura.ieri`: Parameter 'utente' is missing a description. (`app/plugins/commands_modular/aura.py:457`)
- **WARNING missing_param_description** — `aura.oggi`: Parameter 'utente' is missing a description. (`app/plugins/commands_modular/aura.py:452`)
- **WARNING missing_param_description** — `inactivity.dms.template_reminder_set`: Parameter 'text' is missing a description. (`app/plugins/commands_modular/inattivi.py:333`)
- **WARNING missing_param_description** — `mod.channel.template_set`: Parameter 'text' is missing a description. (`app/plugins/commands_modular/moderazione_utenti.py:159`)
- **WARNING missing_param_description** — `resocontocanale.aura.range`: Parameter 'da' is missing a description. (`app/plugins/commands_modular/resoconto.py:662`)
- **WARNING missing_param_description** — `resocontocanale.aura.range`: Parameter 'a' is missing a description. (`app/plugins/commands_modular/resoconto.py:662`)
- **WARNING missing_param_description** — `resocontocanale.aura.ultimi`: Parameter 'quantita' is missing a description. (`app/plugins/commands_modular/resoconto.py:650`)
- **WARNING missing_param_description** — `resocontocanale.aura.ultimi`: Parameter 'unita' is missing a description. (`app/plugins/commands_modular/resoconto.py:650`)
- **WARNING missing_param_description** — `resocontocanale.range`: Parameter 'da' is missing a description. (`app/plugins/commands_modular/resoconto.py:654`)
- **WARNING missing_param_description** — `resocontocanale.range`: Parameter 'a' is missing a description. (`app/plugins/commands_modular/resoconto.py:654`)
- **WARNING missing_param_description** — `resocontocanale.ultimi`: Parameter 'quantita' is missing a description. (`app/plugins/commands_modular/resoconto.py:634`)
- **WARNING missing_param_description** — `resocontocanale.ultimi`: Parameter 'unita' is missing a description. (`app/plugins/commands_modular/resoconto.py:634`)
- **WARNING missing_param_description** — `resocontoserver.aura.range`: Parameter 'da' is missing a description. (`app/plugins/commands_modular/resoconto.py:934`)
- **WARNING missing_param_description** — `resocontoserver.aura.range`: Parameter 'a' is missing a description. (`app/plugins/commands_modular/resoconto.py:934`)
- **WARNING missing_param_description** — `resocontoserver.aura.ultimi`: Parameter 'quantita' is missing a description. (`app/plugins/commands_modular/resoconto.py:922`)
- **WARNING missing_param_description** — `resocontoserver.aura.ultimi`: Parameter 'unita' is missing a description. (`app/plugins/commands_modular/resoconto.py:922`)
- **WARNING missing_param_description** — `resocontoserver.range`: Parameter 'da' is missing a description. (`app/plugins/commands_modular/resoconto.py:926`)
- **WARNING missing_param_description** — `resocontoserver.range`: Parameter 'a' is missing a description. (`app/plugins/commands_modular/resoconto.py:926`)
- **WARNING missing_param_description** — `resocontoserver.ultimi`: Parameter 'quantita' is missing a description. (`app/plugins/commands_modular/resoconto.py:906`)
- **WARNING missing_param_description** — `resocontoserver.ultimi`: Parameter 'unita' is missing a description. (`app/plugins/commands_modular/resoconto.py:906`)
- **WARNING required_param** — `admin.ai.fallback_set`: Parameter 'model' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/admin.py:614`)
- **WARNING required_param** — `admin.ai.model_set`: Parameter 'model' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/admin.py:569`)
- **WARNING required_param** — `admin.barcello.mood_set`: Parameter 'value' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/barcello.py:180`)
- **WARNING required_param** — `admin.footer.template_service_set`: Parameter 'phrase' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/admin.py:807`)
- **WARNING required_param** — `campagne.cap.config_set`: Parameter 'daily_limit' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/messaggi.py:581`)
- **WARNING required_param** — `campagne.prompt.schedule_show`: Parameter 'id_or_name' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:726`)
- **WARNING required_param** — `campagne.quiet.config_set`: Parameter 'start' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/messaggi.py:534`)
- **WARNING required_param** — `campagne.quiet.config_set`: Parameter 'end' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/messaggi.py:534`)
- **WARNING required_param** — `frasi.template_global_set`: Parameter 'text' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:524`)
- **WARNING required_param** — `frasi.template_milestone_set`: Parameter 'threshold' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:481`)
- **WARNING required_param** — `frasi.template_milestone_set`: Parameter 'text' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:481`)
- **WARNING required_param** — `frasi.template_user_set`: Parameter 'text' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:569`)
- **WARNING required_param** — `inactivity.dms.cooldown_set`: Parameter 'days' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:362`)
- **WARNING required_param** — `inactivity.dms.invite_set`: Parameter 'url' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:387`)
- **WARNING required_param** — `inactivity.dms.template_reminder_set`: Parameter 'text' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:333`)
- **WARNING required_param** — `inactivity.grace.config_set`: Parameter 'days' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:263`)
- **WARNING required_param** — `inactivity.policy.default_set`: Parameter 'inactive_days' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:417`)
- **WARNING required_param** — `inactivity.policy.default_set`: Parameter 'window_days' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:418`)
- **WARNING required_param** — `inactivity.policy.default_set`: Parameter 'min_messages' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:419`)
- **WARNING required_param** — `inactivity.policy.default_set`: Parameter 'mode' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:420`)
- **WARNING required_param** — `inactivity.policy.role_set`: Parameter 'inactive_days' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:461`)
- **WARNING required_param** — `inactivity.policy.role_set`: Parameter 'window_days' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:462`)
- **WARNING required_param** — `inactivity.policy.role_set`: Parameter 'min_messages' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:463`)
- **WARNING required_param** — `inactivity.policy.role_set`: Parameter 'mode' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:464`)
- **WARNING required_param** — `inactivity.tempban.config_set`: Parameter 'days' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:310`)
- **WARNING required_param** — `insights.template_set`: Parameter 'text' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:999`)
- **WARNING required_param** — `mod.channel.template_set`: Parameter 'text' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/moderazione_utenti.py:159`)
- **WARNING required_param** — `mod.channel.user_card_set`: Parameter 'enabled' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/moderazione_utenti.py:205`)
- **WARNING required_param** — `qna.bonus_set`: Parameter 'amount' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:936`)
- **WARNING required_param** — `qna.limits_set`: Parameter 'tier' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:905`)
- **WARNING required_param** — `qna.limits_set`: Parameter 'limit' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:905`)

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
- `resocontocanale.aura.ieri`
- `resocontocanale.aura.oggi`
- `resocontocanale.aura.range`
- `resocontocanale.aura.ultimi`
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
- `resocontoserver.aura.ieri`
- `resocontoserver.aura.oggi`
- `resocontoserver.aura.range`
- `resocontoserver.aura.ultimi`
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
