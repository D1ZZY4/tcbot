# PROJECT MAPPING
---
## TREE MAPPING
```
tcbot/
│   alive.py
│   __init__.py
│   __main__.py
│   
├───database
│       admins_db.py
│       bans_db.py
│       cache.py
│       documents.py
│       groups_db.py
│       kicks_db.py
│       mongos.py
│       mutes_db.py
│       queues_db.py
│       roles_db.py
│       types.py
│       users_db.py
│       warns_db.py
│       __init__.py
│       
├───modules
│   │   about.py
│   │   additional.py
│   │   admins.py
│   │   appeals.py
│   │   banning.py
│   │   broadcasting.py
│   │   checking.py
│   │   connecting.py
│   │   disconnecting.py
│   │   greeting.py
│   │   groups.py
│   │   help.py
│   │   kicking.py
│   │   maintenance.py
│   │   muting.py
│   │   privacy.py
│   │   start.py
│   │   stats.py
│   │   unbanning.py
│   │   warnings.py
│   │   __init__.py
│   │   
│   └───helper
│       │   ban_info.py
│       │   decorators.py
│       │   extraction.py
│       │   formatter.py
│       │   keyboards.py
│       │   parse_editmsg.py
│       │   parse_link.py
│       │   parse_logmsg.py
│       │   role_guard.py
│       │   __init__.py
│       │   
│       └───workflows
│               appeal_flow.py
│               ban_flow.py
│               connected_flow.py
│               kicking_flow.py
│               muting_flow.py
│               promote_flow.py
│               proof_flow.py
│               reason_flow.py
│               stats_chats_flow.py
│               stats_flow.py
│               unban_flow.py
│               warning_flow.py
│               __init__.py
│               
└───utils
        dispatch.py
        error_reporter.py
        logger.py
        prefixes.py
        timedate_format.py
        __init__.py
```