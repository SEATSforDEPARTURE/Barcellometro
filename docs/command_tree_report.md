# Command Tree Validation Report

- Commands discovered: **252**
- Errors: **0**
- Warnings: **58**

## Inventory

| Root | Subgroup | Action | Description | Source |
| --- | --- | --- | --- | --- |
| `attivita` | `—` | `ieri` | Report attività di ieri (DM staff) | `app/plugins/commands_modular/attivita.py:567` |
| `attivita` | `—` | `oggi` | Report attività di oggi (DM staff) | `app/plugins/commands_modular/attivita.py:562` |
| `attivita` | `—` | `range` | Report attività per range custom | `app/plugins/commands_modular/attivita.py:592` |
| `attivita` | `—` | `ultimi` | Report attività ultimi N periodi | `app/plugins/commands_modular/attivita.py:580` |
| `audionotes` | `—` | `config_reset` | Reset the audio notes configuration to defaults. | `app/plugins/commands_modular/audio_notes.py:132` |
| `audionotes` | `—` | `config_set` | Update the audio notes configuration. | `app/plugins/commands_modular/audio_notes.py:71` |
| `audionotes` | `—` | `config_show` | Show the audio notes configuration. | `app/plugins/commands_modular/audio_notes.py:121` |
| `audionotes` | `—` | `off` | Disable audio notes. | `app/plugins/commands_modular/audio_notes.py:51` |
| `audionotes` | `—` | `on` | Enable audio notes. | `app/plugins/commands_modular/audio_notes.py:44` |
| `audionotes` | `—` | `status` | Show the audio notes status. | `app/plugins/commands_modular/audio_notes.py:58` |
| `aura` | `—` | `ieri` | Aura di ieri | `app/plugins/commands_modular/aura.py:433` |
| `aura` | `—` | `oggi` | Aura di oggi | `app/plugins/commands_modular/aura.py:428` |
| `aura` | `—` | `range` | Aura per intervallo | `app/plugins/commands_modular/aura.py:439` |
| `aura` | `—` | `ultimi` | Aura ultimi N periodi | `app/plugins/commands_modular/aura.py:411` |
| `bm` | `ai` | `fallback_set` | Set the AI fallback model for a task. | `app/plugins/commands_modular/admin.py:475` |
| `bm` | `ai` | `fallback_show` | Show configured AI fallback models. | `app/plugins/commands_modular/admin.py:494` |
| `bm` | `ai` | `model_set` | Set the AI model for a task. | `app/plugins/commands_modular/admin.py:442` |
| `bm` | `ai` | `model_show` | Show configured AI models. | `app/plugins/commands_modular/admin.py:461` |
| `bm` | `ai` | `off` | Disable the AI service. | `app/plugins/commands_modular/admin.py:432` |
| `bm` | `ai` | `on` | Enable the AI service. | `app/plugins/commands_modular/admin.py:425` |
| `bm` | `ai` | `run` | Run an AI test prompt. | `app/plugins/commands_modular/admin.py:549` |
| `bm` | `ai` | `status` | Show AI service status. | `app/plugins/commands_modular/admin.py:505` |
| `bm` | `backfill` | `config_reset` | Reset backfill configuration to defaults. | `app/plugins/commands_modular/admin.py:399` |
| `bm` | `backfill` | `config_set` | Update backfill configuration. | `app/plugins/commands_modular/admin.py:374` |
| `bm` | `backfill` | `config_show` | Show backfill configuration. | `app/plugins/commands_modular/admin.py:390` |
| `bm` | `backfill` | `off` | Disable backfill. | `app/plugins/commands_modular/admin.py:355` |
| `bm` | `backfill` | `on` | Enable backfill. | `app/plugins/commands_modular/admin.py:348` |
| `bm` | `backfill` | `run` | Run backfill now. | `app/plugins/commands_modular/admin.py:410` |
| `bm` | `backfill` | `status` | Show backfill status. | `app/plugins/commands_modular/admin.py:362` |
| `bm` | `barcello` | `calibrate` | Recalculate Barcello calibration weights. | `app/plugins/commands_modular/barcello.py:182` |
| `bm` | `barcello` | `mood_reset` | Reset the Barcello mood for this channel. | `app/plugins/commands_modular/barcello.py:171` |
| `bm` | `barcello` | `mood_set` | Set the Barcello mood for this channel. | `app/plugins/commands_modular/barcello.py:138` |
| `bm` | `barcello` | `mood_show` | Show the Barcello mood for this channel. | `app/plugins/commands_modular/barcello.py:167` |
| `bm` | `barcello` | `off` | Disable the Barcello trigger for this channel. | `app/plugins/commands_modular/barcello.py:129` |
| `bm` | `barcello` | `on` | Enable the Barcello trigger for this channel. | `app/plugins/commands_modular/barcello.py:125` |
| `bm` | `barcello` | `run` | Run the Barcello analysis. | `app/plugins/commands_modular/barcello.py:1045` |
| `bm` | `barcello` | `status` | Show Barcello trigger status for this channel. | `app/plugins/commands_modular/barcello.py:133` |
| `bm` | `events` | `off` | Disable event collection for this channel. | `app/plugins/commands_modular/admin.py:274` |
| `bm` | `events` | `on` | Enable event collection for this channel. | `app/plugins/commands_modular/admin.py:268` |
| `bm` | `events` | `status` | Show event collection status for this channel. | `app/plugins/commands_modular/admin.py:280` |
| `bm` | `footer` | `off` | Disable footer rendering. | `app/plugins/commands_modular/admin.py:583` |
| `bm` | `footer` | `on` | Enable footer rendering. | `app/plugins/commands_modular/admin.py:573` |
| `bm` | `footer` | `status` | Show footer status and rendered variants. | `app/plugins/commands_modular/admin.py:696` |
| `bm` | `footer` | `template_global_reset` | Reset the global footer template. | `app/plugins/commands_modular/admin.py:633` |
| `bm` | `footer` | `template_global_set` | Set the global footer template. | `app/plugins/commands_modular/admin.py:594` |
| `bm` | `footer` | `template_global_show` | Show the global footer template. | `app/plugins/commands_modular/admin.py:617` |
| `bm` | `footer` | `template_service_reset` | Reset a service-specific footer template. | `app/plugins/commands_modular/admin.py:682` |
| `bm` | `footer` | `template_service_set` | Set a service-specific footer template. | `app/plugins/commands_modular/admin.py:645` |
| `bm` | `footer` | `template_service_show` | Show a service-specific footer template. | `app/plugins/commands_modular/admin.py:664` |
| `bm` | `retention` | `config_reset` | Reset retention configuration to defaults. | `app/plugins/commands_modular/admin.py:337` |
| `bm` | `retention` | `config_set` | Update retention configuration. | `app/plugins/commands_modular/admin.py:312` |
| `bm` | `retention` | `config_show` | Show retention configuration. | `app/plugins/commands_modular/admin.py:328` |
| `bm` | `retention` | `off` | Disable the retention task. | `app/plugins/commands_modular/admin.py:293` |
| `bm` | `retention` | `on` | Enable the retention task. | `app/plugins/commands_modular/admin.py:286` |
| `bm` | `retention` | `status` | Show retention status. | `app/plugins/commands_modular/admin.py:300` |
| `bm` | `—` | `status` | Show the Barcellometro status. | `app/plugins/commands_modular/status.py:13` |
| `campagne` | `cap` | `config_reset` | Reset the daily cap configuration | `app/plugins/commands_modular/messaggi.py:543` |
| `campagne` | `cap` | `config_set` | Set the daily cap configuration | `app/plugins/commands_modular/messaggi.py:526` |
| `campagne` | `cap` | `config_show` | Show the daily cap configuration | `app/plugins/commands_modular/messaggi.py:536` |
| `campagne` | `cap` | `off` | Disable the daily cap | `app/plugins/commands_modular/messaggi.py:507` |
| `campagne` | `cap` | `on` | Enable the daily cap | `app/plugins/commands_modular/messaggi.py:500` |
| `campagne` | `cap` | `status` | Show the daily cap status | `app/plugins/commands_modular/messaggi.py:514` |
| `campagne` | `custom` | `entry_add` | Add a custom campaign entry | `app/plugins/commands_modular/messaggi.py:577` |
| `campagne` | `custom` | `entry_edit` | Edit a custom campaign entry | `app/plugins/commands_modular/messaggi.py:734` |
| `campagne` | `custom` | `entry_list` | List custom campaign entries | `app/plugins/commands_modular/messaggi.py:650` |
| `campagne` | `custom` | `entry_remove` | Remove a custom campaign entry | `app/plugins/commands_modular/messaggi.py:678` |
| `campagne` | `custom` | `entry_run` | Run a custom campaign entry now | `app/plugins/commands_modular/messaggi.py:693` |
| `campagne` | `custom` | `entry_show` | Show a custom campaign entry | `app/plugins/commands_modular/messaggi.py:664` |
| `campagne` | `custom` | `off` | Disable custom campaigns in the current channel | `app/plugins/commands_modular/messaggi.py:554` |
| `campagne` | `custom` | `on` | Enable custom campaigns in the current channel | `app/plugins/commands_modular/messaggi.py:550` |
| `campagne` | `custom` | `status` | Show custom campaign status for the current channel | `app/plugins/commands_modular/messaggi.py:558` |
| `campagne` | `horoscope` | `config_reset` | Reset the horoscope campaign configuration | `app/plugins/commands_modular/messaggi.py:995` |
| `campagne` | `horoscope` | `config_set` | Create or update the horoscope campaign configuration | `app/plugins/commands_modular/messaggi.py:970` |
| `campagne` | `horoscope` | `config_show` | Show the horoscope campaign configuration | `app/plugins/commands_modular/messaggi.py:991` |
| `campagne` | `horoscope` | `off` | Disable horoscope campaigns in the current channel | `app/plugins/commands_modular/messaggi.py:955` |
| `campagne` | `horoscope` | `on` | Enable horoscope campaigns in the current channel | `app/plugins/commands_modular/messaggi.py:951` |
| `campagne` | `horoscope` | `run` | Run the horoscope campaign immediately | `app/plugins/commands_modular/messaggi.py:999` |
| `campagne` | `horoscope` | `status` | Show horoscope campaign status for the current channel | `app/plugins/commands_modular/messaggi.py:959` |
| `campagne` | `news` | `config_reset` | Reset the news campaign configuration | `app/plugins/commands_modular/messaggi.py:891` |
| `campagne` | `news` | `config_set` | Create or update the news campaign configuration | `app/plugins/commands_modular/messaggi.py:865` |
| `campagne` | `news` | `config_show` | Show the news campaign configuration | `app/plugins/commands_modular/messaggi.py:887` |
| `campagne` | `news` | `off` | Disable news campaigns in the current channel | `app/plugins/commands_modular/messaggi.py:849` |
| `campagne` | `news` | `on` | Enable news campaigns in the current channel | `app/plugins/commands_modular/messaggi.py:845` |
| `campagne` | `news` | `run` | Run the news campaign immediately | `app/plugins/commands_modular/messaggi.py:895` |
| `campagne` | `news` | `status` | Show news campaign status for the current channel | `app/plugins/commands_modular/messaggi.py:853` |
| `campagne` | `—` | `off` | Disable campaigns in the current channel | `app/plugins/commands_modular/messaggi.py:422` |
| `campagne` | `—` | `on` | Enable campaigns in the current channel | `app/plugins/commands_modular/messaggi.py:411` |
| `campagne` | `prompt` | `entry_add` | Add a prompt campaign entry | `app/plugins/commands_modular/triggers.py:601` |
| `campagne` | `prompt` | `entry_edit` | Edit a prompt campaign entry | `app/plugins/commands_modular/triggers.py:771` |
| `campagne` | `prompt` | `entry_list` | List prompt campaign entries | `app/plugins/commands_modular/triggers.py:660` |
| `campagne` | `prompt` | `entry_remove` | Remove a prompt campaign entry | `app/plugins/commands_modular/triggers.py:712` |
| `campagne` | `prompt` | `entry_run` | Run a prompt campaign entry now | `app/plugins/commands_modular/triggers.py:727` |
| `campagne` | `prompt` | `entry_show` | Show a prompt campaign entry | `app/plugins/commands_modular/triggers.py:681` |
| `campagne` | `prompt` | `off` | Disable prompt campaigns in the current channel | `app/plugins/commands_modular/triggers.py:570` |
| `campagne` | `prompt` | `on` | Enable prompt campaigns in the current channel | `app/plugins/commands_modular/triggers.py:558` |
| `campagne` | `prompt` | `status` | Show prompt campaign status for the current channel | `app/plugins/commands_modular/triggers.py:582` |
| `campagne` | `quiet` | `config_reset` | Reset quiet hours configuration | `app/plugins/commands_modular/messaggi.py:492` |
| `campagne` | `quiet` | `config_set` | Set quiet hours configuration | `app/plugins/commands_modular/messaggi.py:476` |
| `campagne` | `quiet` | `config_show` | Show quiet hours configuration | `app/plugins/commands_modular/messaggi.py:484` |
| `campagne` | `quiet` | `off` | Disable quiet hours | `app/plugins/commands_modular/messaggi.py:456` |
| `campagne` | `quiet` | `on` | Enable quiet hours | `app/plugins/commands_modular/messaggi.py:449` |
| `campagne` | `quiet` | `status` | Show quiet hours status | `app/plugins/commands_modular/messaggi.py:463` |
| `campagne` | `—` | `status` | Show campaign status for the current channel | `app/plugins/commands_modular/messaggi.py:433` |
| `campagne` | `weather` | `config_reset` | Reset the weather campaign configuration | `app/plugins/commands_modular/messaggi.py:943` |
| `campagne` | `weather` | `config_set` | Create or update the weather campaign configuration | `app/plugins/commands_modular/messaggi.py:918` |
| `campagne` | `weather` | `config_show` | Show the weather campaign configuration | `app/plugins/commands_modular/messaggi.py:939` |
| `campagne` | `weather` | `off` | Disable weather campaigns in the current channel | `app/plugins/commands_modular/messaggi.py:903` |
| `campagne` | `weather` | `on` | Enable weather campaigns in the current channel | `app/plugins/commands_modular/messaggi.py:899` |
| `campagne` | `weather` | `run` | Run the weather campaign immediately | `app/plugins/commands_modular/messaggi.py:947` |
| `campagne` | `weather` | `status` | Show weather campaign status for the current channel | `app/plugins/commands_modular/messaggi.py:907` |
| `commandguard` | `—` | `role_add` | Add a role command policy. | `app/plugins/commands_modular/roles.py:38` |
| `commandguard` | `—` | `role_edit` | Edit a role command policy. | `app/plugins/commands_modular/roles.py:65` |
| `commandguard` | `—` | `role_list` | List all role policies. | `app/plugins/commands_modular/roles.py:120` |
| `commandguard` | `—` | `role_remove` | Remove a role command policy. | `app/plugins/commands_modular/roles.py:87` |
| `commandguard` | `—` | `role_reset` | Reset all policies for a role. | `app/plugins/commands_modular/roles.py:135` |
| `commandguard` | `—` | `role_show` | Show role policies. | `app/plugins/commands_modular/roles.py:103` |
| `commandguard` | `—` | `user_add` | Add a user command policy. | `app/plugins/commands_modular/roles.py:148` |
| `commandguard` | `—` | `user_edit` | Edit a user command policy. | `app/plugins/commands_modular/roles.py:175` |
| `commandguard` | `—` | `user_list` | List all user policies. | `app/plugins/commands_modular/roles.py:230` |
| `commandguard` | `—` | `user_remove` | Remove a user command policy. | `app/plugins/commands_modular/roles.py:197` |
| `commandguard` | `—` | `user_reset` | Reset all policies for a user. | `app/plugins/commands_modular/roles.py:245` |
| `commandguard` | `—` | `user_show` | Show user policies. | `app/plugins/commands_modular/roles.py:213` |
| `domanda` | `—` | `domanda` | Fai una domanda al Q&A | `app/plugins/commands_modular/ask.py:85` |
| `frasi` | `—` | `entry_add` | Add a phrase trigger entry | `app/plugins/commands_modular/triggers.py:244` |
| `frasi` | `—` | `entry_edit` | Edit a phrase trigger entry | `app/plugins/commands_modular/triggers.py:351` |
| `frasi` | `—` | `entry_list` | List phrase trigger entries | `app/plugins/commands_modular/triggers.py:302` |
| `frasi` | `—` | `entry_remove` | Remove a phrase trigger entry | `app/plugins/commands_modular/triggers.py:289` |
| `frasi` | `—` | `entry_show` | Show a phrase trigger entry | `app/plugins/commands_modular/triggers.py:315` |
| `frasi` | `—` | `off` | Disable phrase triggers | `app/plugins/commands_modular/triggers.py:228` |
| `frasi` | `—` | `on` | Enable phrase triggers | `app/plugins/commands_modular/triggers.py:224` |
| `frasi` | `—` | `status` | Show phrase trigger status | `app/plugins/commands_modular/triggers.py:232` |
| `frasi` | `—` | `template_global_reset` | Reset the global phrase template | `app/plugins/commands_modular/triggers.py:499` |
| `frasi` | `—` | `template_global_set` | Set the global phrase template | `app/plugins/commands_modular/triggers.py:469` |
| `frasi` | `—` | `template_global_show` | Show the global phrase template | `app/plugins/commands_modular/triggers.py:483` |
| `frasi` | `—` | `template_milestone_reset` | Reset all milestone templates | `app/plugins/commands_modular/triggers.py:456` |
| `frasi` | `—` | `template_milestone_set` | Create or update a milestone template | `app/plugins/commands_modular/triggers.py:424` |
| `frasi` | `—` | `template_milestone_show` | Show milestone templates | `app/plugins/commands_modular/triggers.py:441` |
| `frasi` | `—` | `template_user_reset` | Reset a user-specific phrase template | `app/plugins/commands_modular/triggers.py:547` |
| `frasi` | `—` | `template_user_set` | Set a user-specific phrase template | `app/plugins/commands_modular/triggers.py:517` |
| `frasi` | `—` | `template_user_show` | Show a user-specific phrase template | `app/plugins/commands_modular/triggers.py:534` |
| `inactivity` | `autokick` | `off` | Disable automatic inactivity actions. | `app/plugins/commands_modular/inattivi.py:207` |
| `inactivity` | `autokick` | `on` | Enable automatic inactivity actions. | `app/plugins/commands_modular/inattivi.py:200` |
| `inactivity` | `autokick` | `status` | Show the automatic inactivity action status. | `app/plugins/commands_modular/inattivi.py:214` |
| `inactivity` | `dms` | `cooldown_reset` | Reset the reminder DM cooldown. | `app/plugins/commands_modular/inattivi.py:363` |
| `inactivity` | `dms` | `cooldown_set` | Set the reminder DM cooldown. | `app/plugins/commands_modular/inattivi.py:346` |
| `inactivity` | `dms` | `cooldown_show` | Show the reminder DM cooldown. | `app/plugins/commands_modular/inattivi.py:353` |
| `inactivity` | `dms` | `invite_reset` | Reset the invite link used in inactivity DMs. | `app/plugins/commands_modular/inattivi.py:391` |
| `inactivity` | `dms` | `invite_set` | Set the invite link used in inactivity DMs. | `app/plugins/commands_modular/inattivi.py:377` |
| `inactivity` | `dms` | `invite_show` | Show the invite link used in inactivity DMs. | `app/plugins/commands_modular/inattivi.py:384` |
| `inactivity` | `dms` | `template_reminder_reset` | Reset the reminder DM template. | `app/plugins/commands_modular/inattivi.py:338` |
| `inactivity` | `dms` | `template_reminder_set` | Set the reminder DM template. | `app/plugins/commands_modular/inattivi.py:319` |
| `inactivity` | `dms` | `template_reminder_show` | Show the reminder DM template. | `app/plugins/commands_modular/inattivi.py:326` |
| `inactivity` | `grace` | `config_reset` | Reset the inactivity grace period configuration. | `app/plugins/commands_modular/inattivi.py:264` |
| `inactivity` | `grace` | `config_set` | Set the inactivity grace period configuration. | `app/plugins/commands_modular/inattivi.py:249` |
| `inactivity` | `grace` | `config_show` | Show the inactivity grace period configuration. | `app/plugins/commands_modular/inattivi.py:256` |
| `inactivity` | `grace` | `off` | Disable the inactivity grace period. | `app/plugins/commands_modular/inattivi.py:233` |
| `inactivity` | `grace` | `on` | Enable the inactivity grace period. | `app/plugins/commands_modular/inattivi.py:224` |
| `inactivity` | `grace` | `status` | Show the inactivity grace period status. | `app/plugins/commands_modular/inattivi.py:240` |
| `inactivity` | `—` | `off` | Disable inactivity moderation. | `app/plugins/commands_modular/inattivi.py:174` |
| `inactivity` | `—` | `on` | Enable inactivity moderation. | `app/plugins/commands_modular/inattivi.py:167` |
| `inactivity` | `policy` | `default_reset` | Reset the default inactivity policy. | `app/plugins/commands_modular/inattivi.py:431` |
| `inactivity` | `policy` | `default_set` | Set the default inactivity policy. | `app/plugins/commands_modular/inattivi.py:405` |
| `inactivity` | `policy` | `default_show` | Show the default inactivity policy. | `app/plugins/commands_modular/inattivi.py:424` |
| `inactivity` | `policy` | `exceptions_add` | Add a role to the inactivity exception list. | `app/plugins/commands_modular/inattivi.py:493` |
| `inactivity` | `policy` | `exceptions_list` | List all inactivity exception roles. | `app/plugins/commands_modular/inattivi.py:530` |
| `inactivity` | `policy` | `exceptions_remove` | Remove a role from the inactivity exception list. | `app/plugins/commands_modular/inattivi.py:507` |
| `inactivity` | `policy` | `exceptions_show` | Show whether a role is excluded from inactivity moderation. | `app/plugins/commands_modular/inattivi.py:521` |
| `inactivity` | `policy` | `role_reset` | Reset an inactivity policy for a role. | `app/plugins/commands_modular/inattivi.py:485` |
| `inactivity` | `policy` | `role_set` | Set an inactivity policy for a role. | `app/plugins/commands_modular/inattivi.py:447` |
| `inactivity` | `policy` | `role_show` | Show an inactivity policy for a role. | `app/plugins/commands_modular/inattivi.py:469` |
| `inactivity` | `—` | `run` | Run the inactivity moderation scan now. | `app/plugins/commands_modular/inattivi.py:544` |
| `inactivity` | `—` | `status` | Show the inactivity moderation status. | `app/plugins/commands_modular/inattivi.py:181` |
| `inactivity` | `tempban` | `config_reset` | Reset the inactivity tempban configuration. | `app/plugins/commands_modular/inattivi.py:311` |
| `inactivity` | `tempban` | `config_set` | Set the inactivity tempban configuration. | `app/plugins/commands_modular/inattivi.py:296` |
| `inactivity` | `tempban` | `config_show` | Show the inactivity tempban configuration. | `app/plugins/commands_modular/inattivi.py:303` |
| `inactivity` | `tempban` | `off` | Disable temporary bans after inactivity kicks. | `app/plugins/commands_modular/inattivi.py:280` |
| `inactivity` | `tempban` | `on` | Enable temporary bans after inactivity kicks. | `app/plugins/commands_modular/inattivi.py:271` |
| `inactivity` | `tempban` | `status` | Show the inactivity tempban status. | `app/plugins/commands_modular/inattivi.py:287` |
| `insights` | `—` | `off` | Disable insights in the current channel | `app/plugins/commands_modular/triggers.py:956` |
| `insights` | `—` | `on` | Enable insights in the current channel | `app/plugins/commands_modular/triggers.py:952` |
| `insights` | `—` | `status` | Show insights status for the current channel | `app/plugins/commands_modular/triggers.py:960` |
| `insights` | `—` | `template_reset` | Reset the insights template to defaults | `app/plugins/commands_modular/triggers.py:1009` |
| `insights` | `—` | `template_set` | Set the insights template | `app/plugins/commands_modular/triggers.py:984` |
| `insights` | `—` | `template_show` | Show the insights template | `app/plugins/commands_modular/triggers.py:997` |
| `mod` | `channel` | `notify_reset` | Reset the moderation notification channel. | `app/plugins/commands_modular/moderazione_utenti.py:171` |
| `mod` | `channel` | `notify_set` | Set the moderation notification channel. | `app/plugins/commands_modular/moderazione_utenti.py:153` |
| `mod` | `channel` | `notify_show` | Show the moderation notification channel. | `app/plugins/commands_modular/moderazione_utenti.py:160` |
| `mod` | `channel` | `off` | Disable moderation notifications for the channel setting. | `app/plugins/commands_modular/moderazione_utenti.py:139` |
| `mod` | `channel` | `on` | Enable moderation notifications for a channel. | `app/plugins/commands_modular/moderazione_utenti.py:123` |
| `mod` | `channel` | `status` | Show the moderation channel configuration status. | `app/plugins/commands_modular/moderazione_utenti.py:146` |
| `mod` | `channel` | `template_reset` | Reset a moderation notification template. | `app/plugins/commands_modular/moderazione_utenti.py:230` |
| `mod` | `channel` | `template_set` | Set a moderation notification template. | `app/plugins/commands_modular/moderazione_utenti.py:179` |
| `mod` | `channel` | `template_show` | Show moderation notification templates. | `app/plugins/commands_modular/moderazione_utenti.py:191` |
| `mod` | `channel` | `user_card_reset` | Reset the moderation notification user card setting. | `app/plugins/commands_modular/moderazione_utenti.py:260` |
| `mod` | `channel` | `user_card_set` | Set whether moderation notifications include the user card. | `app/plugins/commands_modular/moderazione_utenti.py:242` |
| `mod` | `channel` | `user_card_show` | Show whether the moderation notification user card is enabled. | `app/plugins/commands_modular/moderazione_utenti.py:252` |
| `mod` | `users` | `ban` | Ban a user permanently. | `app/plugins/commands_modular/moderazione_utenti.py:322` |
| `mod` | `users` | `ban_list` | List active permanent bans. | `app/plugins/commands_modular/moderazione_utenti.py:333` |
| `mod` | `users` | `grace` | Assign a manual grace period to a user. | `app/plugins/commands_modular/moderazione_utenti.py:373` |
| `mod` | `users` | `grace_list` | List active grace periods. | `app/plugins/commands_modular/moderazione_utenti.py:395` |
| `mod` | `users` | `kick` | Kick a user. | `app/plugins/commands_modular/moderazione_utenti.py:302` |
| `mod` | `users` | `kick_list` | List recent kicks. | `app/plugins/commands_modular/moderazione_utenti.py:313` |
| `mod` | `users` | `tempban` | Ban a user temporarily. | `app/plugins/commands_modular/moderazione_utenti.py:342` |
| `mod` | `users` | `tempban_list` | List active temporary bans. | `app/plugins/commands_modular/moderazione_utenti.py:364` |
| `privacy` | `—` | `off` | Disable voice privacy. | `app/plugins/commands_modular/privacy.py:112` |
| `privacy` | `—` | `on` | Enable voice privacy. | `app/plugins/commands_modular/privacy.py:84` |
| `privacy` | `—` | `status` | Show the current voice privacy status. | `app/plugins/commands_modular/privacy.py:141` |
| `qna` | `—` | `bonus_reset` | Reset a user's QnA bonus | `app/plugins/commands_modular/triggers.py:942` |
| `qna` | `—` | `bonus_set` | Set a QnA bonus for a user | `app/plugins/commands_modular/triggers.py:908` |
| `qna` | `—` | `bonus_show` | Show a user's QnA bonus | `app/plugins/commands_modular/triggers.py:931` |
| `qna` | `—` | `limits_reset` | Reset QnA daily limits to defaults | `app/plugins/commands_modular/triggers.py:898` |
| `qna` | `—` | `limits_set` | Set a QnA daily limit | `app/plugins/commands_modular/triggers.py:877` |
| `qna` | `—` | `limits_show` | Show QnA daily limits | `app/plugins/commands_modular/triggers.py:853` |
| `qna` | `—` | `off` | Disable QnA in the current channel | `app/plugins/commands_modular/triggers.py:843` |
| `qna` | `—` | `on` | Enable QnA in the current channel | `app/plugins/commands_modular/triggers.py:839` |
| `qna` | `—` | `status` | Show QnA status for the current channel | `app/plugins/commands_modular/triggers.py:847` |
| `resocontocanale` | `aura` | `ieri` | Show manual channel aura details for yesterday. | `app/plugins/commands_modular/resoconto.py:496` |
| `resocontocanale` | `aura` | `oggi` | Show manual channel aura details for today. | `app/plugins/commands_modular/resoconto.py:492` |
| `resocontocanale` | `aura` | `range` | Show manual channel aura details for a range. | `app/plugins/commands_modular/resoconto.py:516` |
| `resocontocanale` | `aura` | `ultimi` | Show manual channel aura details for the last window. | `app/plugins/commands_modular/resoconto.py:508` |
| `resocontocanale` | `—` | `off` | Disable automatic channel summaries for the current channel. | `app/plugins/commands_modular/resoconto.py:324` |
| `resocontocanale` | `—` | `on` | Enable automatic channel summaries for the current channel. | `app/plugins/commands_modular/resoconto.py:314` |
| `resocontocanale` | `—` | `schedule_add` | Add a channel summary schedule. | `app/plugins/commands_modular/resoconto.py:372` |
| `resocontocanale` | `—` | `schedule_edit` | Edit a channel summary schedule. | `app/plugins/commands_modular/resoconto.py:400` |
| `resocontocanale` | `—` | `schedule_list` | List channel summary schedules for the current channel. | `app/plugins/commands_modular/resoconto.py:477` |
| `resocontocanale` | `—` | `schedule_remove` | Remove a channel summary schedule. | `app/plugins/commands_modular/resoconto.py:445` |
| `resocontocanale` | `—` | `schedule_show` | Show one channel summary schedule. | `app/plugins/commands_modular/resoconto.py:460` |
| `resocontocanale` | `—` | `status` | Show the channel summary schedule status. | `app/plugins/commands_modular/resoconto.py:334` |
| `resocontoserver` | `aura` | `ieri` | Show manual server aura details for yesterday. | `app/plugins/commands_modular/resoconto.py:697` |
| `resocontoserver` | `aura` | `oggi` | Show manual server aura details for today. | `app/plugins/commands_modular/resoconto.py:692` |
| `resocontoserver` | `aura` | `range` | Show manual server aura details for a range. | `app/plugins/commands_modular/resoconto.py:718` |
| `resocontoserver` | `aura` | `ultimi` | Show manual server aura details for the last window. | `app/plugins/commands_modular/resoconto.py:710` |
| `resocontoserver` | `—` | `off` | Disable automatic server summaries. | `app/plugins/commands_modular/resoconto.py:537` |
| `resocontoserver` | `—` | `on` | Enable automatic server summaries. | `app/plugins/commands_modular/resoconto.py:526` |
| `resocontoserver` | `—` | `schedule_add` | Add a server summary schedule. | `app/plugins/commands_modular/resoconto.py:585` |
| `resocontoserver` | `—` | `schedule_edit` | Edit a server summary schedule. | `app/plugins/commands_modular/resoconto.py:613` |
| `resocontoserver` | `—` | `schedule_list` | List server summary schedules. | `app/plugins/commands_modular/resoconto.py:677` |
| `resocontoserver` | `—` | `schedule_remove` | Remove a server summary schedule. | `app/plugins/commands_modular/resoconto.py:653` |
| `resocontoserver` | `—` | `schedule_show` | Show one server summary schedule. | `app/plugins/commands_modular/resoconto.py:664` |
| `resocontoserver` | `—` | `status` | Show the server summary schedule status. | `app/plugins/commands_modular/resoconto.py:547` |
| `riassunto` | `—` | `ieri` | Riassunto della giornata di ieri | `app/plugins/commands_modular/riassunto.py:1880` |
| `riassunto` | `—` | `oggi` | Riassunto della giornata di oggi | `app/plugins/commands_modular/riassunto.py:1875` |
| `riassunto` | `—` | `range` | Riassunto per intervallo | `app/plugins/commands_modular/riassunto.py:1886` |
| `riassunto` | `—` | `ultimi` | Riassunto ultimi N periodi | `app/plugins/commands_modular/riassunto.py:1856` |
| `stt` | `—` | `config_reset` | Reset the STT configuration to defaults. | `app/plugins/commands_modular/stt.py:114` |
| `stt` | `—` | `config_set` | Update the STT configuration. | `app/plugins/commands_modular/stt.py:61` |
| `stt` | `—` | `config_show` | Show the STT configuration. | `app/plugins/commands_modular/stt.py:100` |
| `translate` | `—` | `config_reset` | Reset the translation configuration to defaults. | `app/plugins/commands_modular/translate.py:73` |
| `translate` | `—` | `config_set` | Update the translation configuration. | `app/plugins/commands_modular/translate.py:31` |
| `translate` | `—` | `config_show` | Show the translation configuration. | `app/plugins/commands_modular/translate.py:59` |
| `voice_ingest` | `—` | `join` | Join a voice channel manually. | `app/plugins/commands_modular/voice_ingest.py:18` |
| `voice_ingest` | `—` | `leave` | Leave the current voice channel manually. | `app/plugins/commands_modular/voice_ingest.py:36` |

## Issues

- **WARNING missing_param_description** — `aura.ieri`: Parameter 'utente' is missing a description. (`app/plugins/commands_modular/aura.py:433`)
- **WARNING missing_param_description** — `aura.oggi`: Parameter 'utente' is missing a description. (`app/plugins/commands_modular/aura.py:428`)
- **WARNING missing_param_description** — `inactivity.dms.template_reminder_set`: Parameter 'text' is missing a description. (`app/plugins/commands_modular/inattivi.py:319`)
- **WARNING missing_param_description** — `mod.channel.template_set`: Parameter 'text' is missing a description. (`app/plugins/commands_modular/moderazione_utenti.py:179`)
- **WARNING missing_param_description** — `resocontocanale.aura.range`: Parameter 'da' is missing a description. (`app/plugins/commands_modular/resoconto.py:516`)
- **WARNING missing_param_description** — `resocontocanale.aura.range`: Parameter 'a' is missing a description. (`app/plugins/commands_modular/resoconto.py:516`)
- **WARNING missing_param_description** — `resocontocanale.aura.ultimi`: Parameter 'quantita' is missing a description. (`app/plugins/commands_modular/resoconto.py:508`)
- **WARNING missing_param_description** — `resocontocanale.aura.ultimi`: Parameter 'unita' is missing a description. (`app/plugins/commands_modular/resoconto.py:508`)
- **WARNING missing_param_description** — `resocontoserver.aura.range`: Parameter 'da' is missing a description. (`app/plugins/commands_modular/resoconto.py:718`)
- **WARNING missing_param_description** — `resocontoserver.aura.range`: Parameter 'a' is missing a description. (`app/plugins/commands_modular/resoconto.py:718`)
- **WARNING missing_param_description** — `resocontoserver.aura.ultimi`: Parameter 'quantita' is missing a description. (`app/plugins/commands_modular/resoconto.py:710`)
- **WARNING missing_param_description** — `resocontoserver.aura.ultimi`: Parameter 'unita' is missing a description. (`app/plugins/commands_modular/resoconto.py:710`)
- **WARNING required_param** — `bm.ai.fallback_set`: Parameter 'model' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/admin.py:478`)
- **WARNING required_param** — `bm.ai.model_set`: Parameter 'model' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/admin.py:445`)
- **WARNING required_param** — `bm.barcello.mood_set`: Parameter 'value' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/barcello.py:138`)
- **WARNING required_param** — `bm.footer.template_service_set`: Parameter 'phrase' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/admin.py:648`)
- **WARNING required_param** — `campagne.cap.config_set`: Parameter 'daily_limit' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/messaggi.py:526`)
- **WARNING required_param** — `campagne.quiet.config_set`: Parameter 'start' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/messaggi.py:476`)
- **WARNING required_param** — `campagne.quiet.config_set`: Parameter 'end' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/messaggi.py:476`)
- **WARNING required_param** — `frasi.template_global_set`: Parameter 'text' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:469`)
- **WARNING required_param** — `frasi.template_milestone_set`: Parameter 'threshold' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:424`)
- **WARNING required_param** — `frasi.template_milestone_set`: Parameter 'text' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:424`)
- **WARNING required_param** — `frasi.template_user_set`: Parameter 'text' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:517`)
- **WARNING required_param** — `inactivity.dms.cooldown_set`: Parameter 'days' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:346`)
- **WARNING required_param** — `inactivity.dms.invite_set`: Parameter 'url' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:377`)
- **WARNING required_param** — `inactivity.dms.template_reminder_set`: Parameter 'text' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:319`)
- **WARNING required_param** — `inactivity.grace.config_set`: Parameter 'days' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:249`)
- **WARNING required_param** — `inactivity.policy.default_set`: Parameter 'inactive_days' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:407`)
- **WARNING required_param** — `inactivity.policy.default_set`: Parameter 'window_days' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:408`)
- **WARNING required_param** — `inactivity.policy.default_set`: Parameter 'min_messages' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:409`)
- **WARNING required_param** — `inactivity.policy.default_set`: Parameter 'mode' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:410`)
- **WARNING required_param** — `inactivity.policy.role_set`: Parameter 'inactive_days' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:450`)
- **WARNING required_param** — `inactivity.policy.role_set`: Parameter 'window_days' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:451`)
- **WARNING required_param** — `inactivity.policy.role_set`: Parameter 'min_messages' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:452`)
- **WARNING required_param** — `inactivity.policy.role_set`: Parameter 'mode' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:453`)
- **WARNING required_param** — `inactivity.tempban.config_set`: Parameter 'days' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/inattivi.py:296`)
- **WARNING required_param** — `insights.template_set`: Parameter 'text' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:984`)
- **WARNING required_param** — `mod.channel.template_set`: Parameter 'text' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/moderazione_utenti.py:179`)
- **WARNING required_param** — `mod.channel.user_card_set`: Parameter 'enabled' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/moderazione_utenti.py:242`)
- **WARNING required_param** — `qna.bonus_set`: Parameter 'amount' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:908`)
- **WARNING required_param** — `qna.limits_set`: Parameter 'tier' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:877`)
- **WARNING required_param** — `qna.limits_set`: Parameter 'limit' is required in a configuration-style command; verify it is indispensable. (`app/plugins/commands_modular/triggers.py:877`)

## Legacy alias review

- **WARNING legacy_alias** — `app/plugins/commands_modular/roles.py`: `if not await check_permission(interaction, "bm.commandguard.role_add", ctx, legacy_aliases=["bm.role.set_role"]):` (`app/plugins/commands_modular/roles.py:45`)
- **WARNING legacy_alias** — `app/plugins/commands_modular/roles.py`: `if not await check_permission(interaction, "bm.commandguard.role_edit", ctx, legacy_aliases=["bm.role.set_role"]):` (`app/plugins/commands_modular/roles.py:72`)
- **WARNING legacy_alias** — `app/plugins/commands_modular/roles.py`: `if not await check_permission(interaction, "bm.commandguard.user_add", ctx, legacy_aliases=["bm.role.set_user"]):` (`app/plugins/commands_modular/roles.py:155`)
- **WARNING legacy_alias** — `app/plugins/commands_modular/roles.py`: `if not await check_permission(interaction, "bm.commandguard.user_edit", ctx, legacy_aliases=["bm.role.set_user"]):` (`app/plugins/commands_modular/roles.py:182`)
- **WARNING legacy_alias** — `app/plugins/commands_modular/triggers.py`: `scope = await _require_channel(interaction, "frasi.add")` (`app/plugins/commands_modular/triggers.py:252`)
- **WARNING legacy_alias** — `app/plugins/commands_modular/triggers.py`: `scope = await _require_channel(interaction, "frasi.remove")` (`app/plugins/commands_modular/triggers.py:290`)
- **WARNING legacy_alias** — `app/plugins/commands_modular/triggers.py`: `scope = await _require_channel(interaction, "frasi.list")` (`app/plugins/commands_modular/triggers.py:303`)
- **WARNING legacy_alias** — `app/plugins/commands_modular/triggers.py`: `scope = await _require_channel(interaction, "frasi.milestone_global_set")` (`app/plugins/commands_modular/triggers.py:425`)
- **WARNING legacy_alias** — `app/plugins/commands_modular/triggers.py`: `scope = await _require_channel(interaction, "frasi.milestone_global_list", "frasi.milestone_global_status")` (`app/plugins/commands_modular/triggers.py:442`)
- **WARNING legacy_alias** — `app/plugins/commands_modular/triggers.py`: `scope = await _require_channel(interaction, "frasi.milestone_global_remove")` (`app/plugins/commands_modular/triggers.py:457`)
- **WARNING legacy_alias** — `app/plugins/commands_modular/triggers.py`: `scope = await _require_channel(interaction, "frasi.template_set")` (`app/plugins/commands_modular/triggers.py:470`)
- **WARNING legacy_alias** — `app/plugins/commands_modular/triggers.py`: `scope = await _require_channel(interaction, "frasi.template_show")` (`app/plugins/commands_modular/triggers.py:484`)
- **WARNING legacy_alias** — `app/plugins/commands_modular/triggers.py`: `scope = await _require_channel(interaction, "frasi.template_reset")` (`app/plugins/commands_modular/triggers.py:500`)
- **WARNING legacy_alias** — `app/plugins/commands_modular/triggers.py`: `scope = await _require_channel(interaction, "frasi.userphrase_set")` (`app/plugins/commands_modular/triggers.py:518`)
- **WARNING legacy_alias** — `app/plugins/commands_modular/triggers.py`: `scope = await _require_channel(interaction, "frasi.userphrase_show")` (`app/plugins/commands_modular/triggers.py:535`)
- **WARNING legacy_alias** — `app/plugins/commands_modular/triggers.py`: `scope = await _require_channel(interaction, "frasi.userphrase_remove")` (`app/plugins/commands_modular/triggers.py:548`)

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
- `resocontocanale.off`
- `resocontocanale.on`
- `resocontocanale.schedule_add`
- `resocontocanale.schedule_edit`
- `resocontocanale.schedule_list`
- `resocontocanale.schedule_remove`
- `resocontocanale.schedule_show`
- `resocontocanale.status`
- `resocontoserver.aura.ieri`
- `resocontoserver.aura.oggi`
- `resocontoserver.aura.range`
- `resocontoserver.aura.ultimi`
- `resocontoserver.off`
- `resocontoserver.on`
- `resocontoserver.schedule_add`
- `resocontoserver.schedule_edit`
- `resocontoserver.schedule_list`
- `resocontoserver.schedule_remove`
- `resocontoserver.schedule_show`
- `resocontoserver.status`
- `riassunto.ieri`
- `riassunto.oggi`
- `riassunto.range`
- `riassunto.ultimi`

## Usage

- Run `python -m scripts.validate_commands` for a console report.
- Run `python -m scripts.validate_commands --write-report` to refresh this markdown file.
- Run `pytest tests/test_command_standard_validator.py` to fail CI on validator errors.
