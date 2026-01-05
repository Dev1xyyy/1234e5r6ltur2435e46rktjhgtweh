import sqlite3
import json
import hashlib
import threading
import random
import string
import os
from datetime import datetime
import server_config as cfg
import server_state as state
import server_utils as utils
from server_voice import voice_server

def process_request(req):
    action = req.get('action')
    payload = req.get('payload', {})

    with state.db_lock:
        db = sqlite3.connect(cfg.DB_NAME)
        cur = db.cursor()
        try:
            if action == 'register':
                email, user, pwd = payload['email'], payload['username'].lower(), payload['password']
                cur.execute("SELECT id FROM users WHERE email=? OR username=?", (email, user))
                if cur.fetchone(): return {"status": "error", "msg": "Занято"}
                disc = str(random.randint(1000, 9999))
                p_hash = hashlib.sha256(pwd.encode()).hexdigest()
                code = ''.join(random.choices(string.digits, k=6))
                color = random.choice(['#5865F2', '#EB459E', '#F2CC58', '#23A559'])
                cur.execute("INSERT INTO users (email, username, discriminator, password_hash, verification_code, avatar_color, created_at) VALUES (?,?,?,?,?,?,?)",
                            (email, user, disc, p_hash, code, color, str(datetime.now())))
                uid = cur.lastrowid
                db.commit()
                threading.Thread(target=utils.send_email, args=(email, code)).start()
                return {"status": "ok", "user_id": uid}

            elif action == 'login':
                login, pwd = payload['login'].lower(), hashlib.sha256(payload['password'].encode()).hexdigest()
                cur.execute("SELECT * FROM users WHERE (email=? OR username=?) AND password_hash=?", (login, login, pwd))
                u = cur.fetchone()
                if not u: return {"status": "error", "msg": "Неверно"}
                if u[15]: return {"status": "error", "msg": "Пользователь заблокирован"} 
                return {"status": "ok", "user": {
                    "id": u[0], "email": u[1], "username": u[2], "discriminator": u[3], "is_verified": u[5], 
                    "color": u[7], "image": u[8], "decoration": u[9], "banner": u[10], "banner_image": u[11], 
                    "about_me": u[12], "custom_status": u[13], "nickname_color": u[14], "is_admin": u[17],
                    "chat_bg": u[18], "units": u[19] if u[19] is not None else 0,
                    "profile_music": u[20] if len(u) > 20 else None
                }}

            elif action == 'check_ban_status':
                cur.execute("SELECT is_blocked, ban_reason, username, discriminator FROM users WHERE id=?", (payload['id'],))
                res = cur.fetchone()
                if res and res[0] == 1: return {"status": "banned", "reason": res[1], "tag": f"{res[2]}#{res[3]}"}
                return {"status": "ok"}

            elif action == 'verify':
                uid, code = payload['id'], payload['code']
                cur.execute("SELECT verification_code FROM users WHERE id=?", (uid,))
                res = cur.fetchone()
                if res and code == res[0]:
                    cur.execute("UPDATE users SET is_verified=1 WHERE id=?", (uid,))
                    db.commit(); return {"status": "ok"}
                return {"status": "error", "msg": "Неверный код"}

            # --- VOICE CALL LOGIC ---
            elif action == 'join_voice':
                uid = payload['user_id']
                channel_id = str(payload['chat_id'])
                
                voice_server.join_channel(uid, channel_id)
                
                if payload['chat_type'] == 'private':
                    try:
                        parts = channel_id.split('_')
                        if len(parts) == 3:
                            id1, id2 = int(parts[1]), int(parts[2])
                            target_id = id1 if id1 != uid else id2
                            
                            # Ringing event
                            utils.broadcast_to_user(target_id, {
                                "event": "voice_ring", 
                                "caller_id": uid,
                                "chat_id": channel_id,
                                "chat_type": "private"
                            })
                            
                            event = {"event": "voice_update", "type": "join", "user_id": uid, "chat_id": uid} # Send caller ID as chat_id for mapping
                            utils.broadcast_to_user(target_id, event)
                            utils.broadcast_to_user(uid, event)
                    except: pass
                else:
                    event = {"event": "voice_update", "type": "join", "user_id": uid, "chat_id": channel_id}
                    cur.execute("SELECT user_id FROM group_members WHERE group_id=?", (channel_id,))
                    for m in cur.fetchall():
                        utils.broadcast_to_user(m[0], event)
                        
                return {"status": "ok"}

            elif action == 'leave_voice':
                uid = payload['user_id']
                channel_id = str(payload['chat_id'])
                voice_server.leave_channel(uid)
                
                # Check empty logic removed for simplicity to ensure "leave" event always fires
                is_empty = False 
                
                if payload['chat_type'] == 'private':
                    try:
                        parts = channel_id.split('_')
                        if len(parts) == 3:
                            id1, id2 = int(parts[1]), int(parts[2])
                            target_id = id1 if id1 != uid else id2
                            
                            event = {"event": "voice_update", "type": "leave", "user_id": uid, "chat_id": uid, "is_empty": is_empty}
                            utils.broadcast_to_user(target_id, event)
                    except: pass
                else:
                    event = {"event": "voice_update", "type": "leave", "user_id": uid, "chat_id": channel_id, "is_empty": is_empty}
                    cur.execute("SELECT user_id FROM group_members WHERE group_id=?", (channel_id,))
                    for m in cur.fetchall():
                        utils.broadcast_to_user(m[0], event)
                        
                return {"status": "ok"}
            
            elif action == 'voice_state':
                # NEW: Sync Mute/Deafen state
                uid = payload['user_id']
                channel_id = str(payload['chat_id'])
                is_muted = payload.get('is_muted', False)
                is_deafened = payload.get('is_deafened', False)
                
                event = {
                    "event": "voice_state_update",
                    "user_id": uid,
                    "chat_id": channel_id,
                    "is_muted": is_muted,
                    "is_deafened": is_deafened
                }
                
                if payload['chat_type'] == 'private':
                    try:
                        parts = channel_id.split('_')
                        if len(parts) == 3:
                            id1, id2 = int(parts[1]), int(parts[2])
                            target_id = id1 if id1 != uid else id2
                            utils.broadcast_to_user(target_id, event)
                    except: pass
                else:
                    cur.execute("SELECT user_id FROM group_members WHERE group_id=?", (channel_id,))
                    for m in cur.fetchall():
                        if m[0] != uid: # Don't send back to self necessarily, but useful for confirm
                            utils.broadcast_to_user(m[0], event)
                
                return {"status": "ok"}

            elif action == 'get_voice_participants':
                channel_id = str(payload['chat_id'])
                participants = []
                with voice_server.lock:
                    for uid, cid in voice_server.user_channels.items():
                        if cid == channel_id:
                            cur.execute("SELECT id, username, avatar_color, avatar_image FROM users WHERE id=?", (uid,))
                            u = cur.fetchone()
                            if u:
                                participants.append({
                                    "id": u[0], "username": u[1], "color": u[2], "image": u[3]
                                })
                return {"status": "ok", "participants": participants}

            # --- ASSETS SYNC ---
            elif action == 'get_assets_index':
                assets = {"banners": [], "rams": [], "chat_backgrounds": [], "bot_avatar": []}
                if os.path.exists(cfg.ASSETS_BANNERS_DIR):
                    for f in os.listdir(cfg.ASSETS_BANNERS_DIR):
                        if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
                            assets["banners"].append({"name": f, "hash": utils.get_file_hash(os.path.join(cfg.ASSETS_BANNERS_DIR, f))})
                if os.path.exists(cfg.ASSETS_RAMS_DIR):
                    for f in os.listdir(cfg.ASSETS_RAMS_DIR):
                        if f.lower().endswith(('.gif', '.png')):
                            assets["rams"].append({"name": f, "hash": utils.get_file_hash(os.path.join(cfg.ASSETS_RAMS_DIR, f))})
                if os.path.exists(cfg.ASSETS_CHAT_BG_DIR):
                    for f in os.listdir(cfg.ASSETS_CHAT_BG_DIR):
                        if f.lower().endswith(('.png', '.jpg', '.jpeg')):
                            assets["chat_backgrounds"].append({"name": f, "hash": utils.get_file_hash(os.path.join(cfg.ASSETS_CHAT_BG_DIR, f))})
                if os.path.exists(cfg.ASSETS_BOT_AVATAR_DIR):
                    for f in os.listdir(cfg.ASSETS_BOT_AVATAR_DIR):
                        if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
                            assets["bot_avatar"].append({"name": f, "hash": utils.get_file_hash(os.path.join(cfg.ASSETS_BOT_AVATAR_DIR, f))})
                return {"status": "ok", "assets": assets}

            elif action == 'get_asset_file':
                asset_type = payload['type']
                filename = payload['filename']
                if ".." in filename or "/" in filename or "\\" in filename: return {"status": "error", "msg": "Invalid filename"}
                type_dirs = {"banners": cfg.ASSETS_BANNERS_DIR, "rams": cfg.ASSETS_RAMS_DIR, "chat_backgrounds": cfg.ASSETS_CHAT_BG_DIR, "bot_avatar": cfg.ASSETS_BOT_AVATAR_DIR}
                if asset_type not in type_dirs: return {"status": "error", "msg": "Invalid type"}
                path = os.path.join(type_dirs[asset_type], filename)
                b64 = utils.load_file_b64(path)
                return {"status": "ok", "b64": b64, "filename": filename} if b64 else {"status": "error", "msg": "Not found"}

            # --- USER CACHE SYNC ---
            elif action == 'get_user_cache_index':
                user_id = payload['user_id']
                cache_dir = os.path.join(cfg.UPLOAD_DIR, f"user_cache_{user_id}")
                files = []
                if os.path.exists(cache_dir):
                    for f in os.listdir(cache_dir):
                        path = os.path.join(cache_dir, f)
                        if os.path.isfile(path): files.append({"name": f, "hash": utils.get_file_hash(path)})
                return {"status": "ok", "files": files}

            elif action == 'upload_cache_file':
                user_id, filename, b64_data = payload['user_id'], payload['filename'], payload['b64']
                if ".." in filename: return {"status": "error"}
                cache_dir = os.path.join(cfg.UPLOAD_DIR, f"user_cache_{user_id}")
                if not os.path.exists(cache_dir): os.makedirs(cache_dir)
                try:
                    with open(os.path.join(cache_dir, filename), "wb") as f:
                        f.write(base64.b64decode(b64_data))
                    return {"status": "ok"}
                except: return {"status": "error"}

            elif action == 'get_cache_file':
                user_id, filename = payload['user_id'], payload['filename']
                if ".." in filename: return {"status": "error"}
                path = os.path.join(cfg.UPLOAD_DIR, f"user_cache_{user_id}", filename)
                b64 = utils.load_file_b64(path)
                return {"status": "ok", "b64": b64} if b64 else {"status": "error"}

            # --- FILES ---
            elif action == 'get_file_content':
                fname = payload['filename']
                is_sticker, is_nft = payload.get('is_sticker', False), payload.get('is_nft', False)
                path = fname 
                if is_sticker: path = os.path.join(cfg.STICKERS_DIR, fname)
                elif is_nft: path = os.path.join(cfg.NFTS_DIR, fname)
                else: path = os.path.join(cfg.UPLOAD_DIR, fname)
                if ".." in path: return {"status": "error"}
                return {"status": "ok", "b64": utils.load_file_b64(path)}

            elif action == 'get_stickers_index':
                index = {}
                if os.path.exists(cfg.STICKERS_DIR):
                    for pack in os.listdir(cfg.STICKERS_DIR):
                        pack_path = os.path.join(cfg.STICKERS_DIR, pack)
                        if os.path.isdir(pack_path):
                            files = [f for f in os.listdir(pack_path) if f.lower().endswith(('.png', '.gif', '.jpg'))]
                            if files: index[pack] = files
                return {"status": "ok", "data": index}
            
            elif action == 'get_server_nfts_assets':
                files = []
                if os.path.exists(cfg.NFTS_DIR):
                    files = [f for f in os.listdir(cfg.NFTS_DIR) if f.lower().endswith(('.gif', '.png', '.jpg'))]
                return {"status": "ok", "files": files}

            elif action == 'mint_gift':
                sender, target, fname = payload['sender_id'], payload['target_id'], payload['filename']
                name = os.path.splitext(fname)[0].replace('_', ' ').title()
                price = 100
                cur.execute("SELECT units FROM users WHERE id=?", (sender,))
                res = cur.fetchone()
                current_units = res[0] if res else 0
                if current_units < price: return {"status": "error", "msg": "Недостаточно Units"}
                cur.execute("UPDATE users SET units = units - ? WHERE id=?", (price, sender))
                cur.execute("INSERT INTO nfts (owner_id, filename, name, minted_at) VALUES (?,?,?,?)", (target, fname, name, str(datetime.now())))
                cur.execute("INSERT INTO messages (sender_id, target_id, target_type, content, timestamp, attachment_type, attachment_filename, status) VALUES (?,?,?,?,?,?,?,?)", (sender, target, 'private', name, str(datetime.now()), 'gift', fname, 'sent'))
                db.commit()
                utils.broadcast_to_user(target, {"event": "new_gift", "from": sender}); utils.broadcast_to_user(target, {"event": "gift_anim"})
                utils.broadcast_to_user(sender, {"event": "gift_anim"})
                return {"status": "ok", "new_balance": current_units - price}

            elif action == 'get_user_gifts':
                uid = payload['user_id']
                viewer = payload.get('viewer_id')
                if str(uid) == "0": return {"status": "ok", "gifts": []}
                if str(viewer) == str(uid): cur.execute("SELECT id, filename, name, minted_at, is_hidden FROM nfts WHERE owner_id=?", (uid,))
                else: cur.execute("SELECT id, filename, name, minted_at, is_hidden FROM nfts WHERE owner_id=? AND is_hidden=0", (uid,))
                return {"status": "ok", "gifts": [{"id": r[0], "filename": r[1], "name": r[2], "date": r[3], "hidden": r[4]} for r in cur.fetchall()]}

            elif action == 'get_friends_data':
                uid = payload['id']
                cur.execute('''SELECT u.id, u.username, u.discriminator, u.avatar_color, u.avatar_image, u.about_me, u.banner_color, u.banner_image, u.custom_status, u.nickname_color, u.avatar_decoration, u.units, u.profile_music
                    FROM users u JOIN friends f ON (u.id=f.friend_id OR u.id=f.user_id)
                    WHERE (f.user_id=? OR f.friend_id=?) AND f.status='accepted' AND u.id!=?''', (uid, uid, uid))
                
                friends = []
                for r in cur.fetchall():
                    friends.append({
                        "id": r[0], "username": r[1], "tag": r[2], "color": r[3], "image": r[4], 
                        "about": r[5], "banner": r[6], "banner_image": r[7], "status_text": r[8], 
                        "nick_color": r[9], "decoration": r[10], 
                        "units": r[11] if r[11] is not None else 0,
                        "profile_music": r[12]
                    })
                
                cur.execute("SELECT units FROM users WHERE id=?", (uid,))
                my_res = cur.fetchone()
                my_units = my_res[0] if my_res else 0

                try:
                    cur.execute("SELECT * FROM users WHERE id=0")
                    bot = cur.fetchone()
                    if bot:
                        friends.insert(0, {
                            "id": 0, "username": "NovCord", "tag": "0000", "color": "#5865F2", "image": None,
                            "about": "Official Bot", "banner": "black", "banner_image": None,
                            "status_text": "SYSTEM", "nick_color": "white", "decoration": None, "units": 0,
                            "is_bot": True, "profile_music": None
                        })
                except: pass

                cur.execute("SELECT u.id, u.username, u.discriminator FROM users u JOIN friends f ON u.id=f.user_id WHERE f.friend_id=? AND f.status='pending'", (uid,))
                reqs = [{"id":r[0], "username":r[1], "tag":r[2]} for r in cur.fetchall()]
                
                cur.execute('''SELECT g.id, g.name, g.avatar_color, g.owner_id, g.avatar_image, g.banner_image FROM groups g JOIN group_members gm ON g.id=gm.group_id WHERE gm.user_id=?''', (uid,))
                groups = [{"id":r[0], "name":r[1], "color":r[2], "owner":r[3], "image": r[4], "banner": r[5], "type": "group"} for r in cur.fetchall()]
                
                return {"status": "ok", "friends": friends, "requests": reqs, "groups": groups, "my_units": my_units}

            elif action == 'add_friend':
                uid, target = payload['from'], payload['target'].lower()
                try:
                    name, tag = target.split('#')
                    cur.execute("SELECT id FROM users WHERE username=? AND discriminator=?", (name, tag))
                    res = cur.fetchone()
                    if not res: return {"status": "error", "msg": "Не найден"}
                    tid = res[0]
                    if tid == uid: return {"status": "error", "msg": "Это вы"}
                    cur.execute("SELECT * FROM friends WHERE (user_id=? AND friend_id=?) OR (user_id=? AND friend_id=?)", (uid, tid, tid, uid))
                    if cur.fetchone(): return {"status": "error", "msg": "Уже друзья"}
                    cur.execute("INSERT INTO friends (user_id, friend_id, status) VALUES (?,?,'pending')", (uid, tid))
                    db.commit(); utils.broadcast_to_user(tid, {"event": "update_friends"})
                    return {"status": "ok"}
                except: return {"status": "error", "msg": "Формат: User#0000"}

            elif action == 'accept_friend':
                cur.execute("UPDATE friends SET status='accepted' WHERE user_id=? AND friend_id=?", (payload['target_id'], payload['my_id']))
                db.commit(); utils.broadcast_to_user(payload['target_id'], {"event": "update_friends"})
                return {"status": "ok"}
            
            elif action == 'block_user':
                uid, tid = payload['user_id'], payload['blocked_id']
                if str(tid) == "0": return {"status": "error", "msg": "Cannot block bot"}
                cur.execute("INSERT OR IGNORE INTO user_blocks (user_id, blocked_id) VALUES (?,?)", (uid, tid))
                db.commit()
                utils.broadcast_to_user(tid, {"event": "update_friends"}) 
                return {"status": "ok"}
            
            elif action == 'unblock_user':
                uid, tid = payload['user_id'], payload['blocked_id']
                cur.execute("DELETE FROM user_blocks WHERE user_id=? AND blocked_id=?", (uid, tid))
                db.commit()
                return {"status": "ok"}

            elif action == 'delete_chat_history':
                uid, tid = payload['user_id'], payload['target_id']
                if str(tid) == "0": return {"status": "error", "msg": "Cannot delete bot chat"}
                cur.execute("DELETE FROM messages WHERE (sender_id=? AND target_id=? AND target_type='private') OR (sender_id=? AND target_id=? AND target_type='private')", (uid, tid, tid, uid))
                db.commit()
                utils.broadcast_to_user(uid, {"event": "new_msg", "chat_id": tid, "type": "private"}) 
                utils.broadcast_to_user(tid, {"event": "new_msg", "chat_id": uid, "type": "private"})
                return {"status": "ok"}

            elif action == 'create_group':
                members = payload['members']
                if 'invite_user' in payload and payload['invite_user']:
                    try:
                        nm, tg = payload['invite_user'].lower().split('#')
                        cur.execute("SELECT id FROM users WHERE username=? AND discriminator=?", (nm, tg))
                        usr = cur.fetchone()
                        if usr:
                            cur.execute("SELECT * FROM group_blacklist WHERE user_id=?", (usr[0],))
                            if usr[0] not in members: members.append(usr[0])
                    except: pass
                cur.execute("INSERT INTO groups (name, owner_id, avatar_color) VALUES (?,?,?)", (payload['name'], payload['owner_id'], '#5865F2'))
                gid = cur.lastrowid
                for m_id in members: cur.execute("INSERT INTO group_members (group_id, user_id) VALUES (?,?)", (gid, m_id))
                db.commit()
                for m_id in members: utils.broadcast_to_user(m_id, {"event": "update_friends"})
                return {"status": "ok"}
            
            elif action == 'update_group':
                gid = payload['group_id']
                fname = utils.save_file_to_disk(payload['image_b64']) if payload.get('image_b64') else None
                bfname = utils.save_file_to_disk(payload['banner_b64'], "gif" if payload.get('is_gif_bn') else "png") if payload.get('banner_b64') else None
                sql = "UPDATE groups SET name=?, avatar_color=?"; params = [payload['name'], payload['color']]
                if fname: sql += ", avatar_image=?"; params.append(fname)
                if bfname: sql += ", banner_image=?"; params.append(bfname)
                sql += " WHERE id=?"; params.append(gid)
                cur.execute(sql, params); db.commit()
                cur.execute("SELECT user_id FROM group_members WHERE group_id=?", (gid,))
                for m in cur.fetchall(): utils.broadcast_to_user(m[0], {"event": "update_friends"})
                return {"status": "ok"}

            elif action == 'invite_group_user':
                gid, target = payload['group_id'], payload['target']
                try:
                    tid = None
                    if isinstance(target, int): tid = target
                    else:
                        nm, tg = target.lower().split('#')
                        cur.execute("SELECT id FROM users WHERE username=? AND discriminator=?", (nm, tg))
                        res = cur.fetchone(); 
                        if res: tid = res[0]
                    if not tid: return {"status": "error", "msg": "Пользователь не найден"}
                    cur.execute("SELECT * FROM group_blacklist WHERE group_id=? AND user_id=?", (gid, tid))
                    if cur.fetchone(): return {"status": "error", "msg": "Пользователь в черном списке"}
                    cur.execute("SELECT * FROM group_members WHERE group_id=? AND user_id=?", (gid, tid))
                    if cur.fetchone(): return {"status": "error", "msg": "Уже участник"}
                    cur.execute("INSERT INTO group_members (group_id, user_id) VALUES (?,?)", (gid, tid))
                    db.commit(); utils.broadcast_to_user(tid, {"event": "update_friends"})
                    return {"status": "ok", "msg": "Приглашен"}
                except: return {"status": "error", "msg": "Ошибка"}

            elif action == 'leave_group':
                gid, uid = payload['group_id'], payload['user_id']
                cur.execute("DELETE FROM group_members WHERE group_id=? AND user_id=?", (gid, uid))
                db.commit()
                cur.execute("SELECT user_id FROM group_members WHERE group_id=?", (gid,))
                for m in cur.fetchall(): utils.broadcast_to_user(m[0], {"event": "new_msg", "chat_id": gid, "type": "group"})
                return {"status": "ok"}
            
            elif action == 'delete_group':
                gid, uid = payload['group_id'], payload['user_id']
                cur.execute("SELECT owner_id FROM groups WHERE id=?", (gid,))
                res = cur.fetchone()
                if res and res[0] == uid:
                    cur.execute("SELECT user_id FROM group_members WHERE group_id=?", (gid,))
                    members = cur.fetchall()
                    cur.execute("DELETE FROM group_members WHERE group_id=?", (gid,))
                    cur.execute("DELETE FROM groups WHERE id=?", (gid,))
                    cur.execute("DELETE FROM group_blacklist WHERE group_id=?", (gid,))
                    db.commit()
                    for m in members: utils.broadcast_to_user(m[0], {"event": "update_friends"})
                    return {"status": "ok"}
                return {"status": "error", "msg": "Not owner"}

            elif action == 'kick_group_user':
                gid, uid = payload['group_id'], payload['user_id']
                cur.execute("DELETE FROM group_members WHERE group_id=? AND user_id=?", (gid, uid)); db.commit()
                utils.broadcast_to_user(uid, {"event": "update_friends"})
                cur.execute("SELECT user_id FROM group_members WHERE group_id=?", (gid,))
                for m in cur.fetchall(): utils.broadcast_to_user(m[0], {"event": "new_msg", "chat_id": gid, "type": "group"})
                return {"status": "ok"}

            elif action == 'ban_group_user':
                gid, uid = payload['group_id'], payload['user_id']
                cur.execute("DELETE FROM group_members WHERE group_id=? AND user_id=?", (gid, uid))
                cur.execute("INSERT INTO group_blacklist (group_id, user_id) VALUES (?,?)", (gid, uid)); db.commit()
                utils.broadcast_to_user(uid, {"event": "update_friends"})
                return {"status": "ok"}

            elif action == 'unban_group_user':
                gid, uid = payload['group_id'], payload['user_id']
                cur.execute("DELETE FROM group_blacklist WHERE group_id=? AND user_id=?", (gid, uid)); db.commit()
                return {"status": "ok"}

            elif action == 'get_group_blacklist':
                cur.execute('''SELECT u.id, u.username, u.discriminator, u.avatar_image FROM users u JOIN group_blacklist gb ON u.id=gb.user_id WHERE gb.group_id=?''', (payload['group_id'],))
                return {"status": "ok", "blacklist": [{"id":r[0], "username":r[1], "tag":r[2], "image":r[3]} for r in cur.fetchall()]}

            elif action == 'get_group_members':
                cur.execute('''SELECT u.id, u.username, u.discriminator, u.avatar_color, u.avatar_image, u.nickname_color, u.avatar_decoration, u.units
                               FROM users u JOIN group_members gm ON u.id=gm.user_id WHERE gm.group_id=?''', (payload['group_id'],))
                return {"status": "ok", "members": [{"id":r[0], "username":r[1], "tag":r[2], "color":r[3], "image":r[4], "nick_color":r[5], "decoration":r[6], "units": r[7] if r[7] is not None else 0} for r in cur.fetchall()]}

            elif action == 'send_msg':
                sender, target = payload['sender'], payload['target']
                
                if payload['type'] == 'private':
                    cur.execute("SELECT * FROM user_blocks WHERE user_id=? AND blocked_id=?", (target, sender))
                    if cur.fetchone():
                        return {"status": "blocked"}

                att_fname = None
                if payload.get('att_data'):
                    ext = "mp4" if payload.get('att_type') == 'video' else "png"
                    if payload.get('att_type') == 'gif': ext = "gif"
                    if payload.get('att_type') == 'audio': ext = "mp3"
                    if payload.get('att_type') == 'voice': ext = "wav"
                    att_fname = utils.save_file_to_disk(payload['att_data'], ext)
                elif payload.get('att_type') == 'sticker':
                    att_fname = payload['text'] 
                elif payload.get('att_file'): # Forwarded file logic
                    att_fname = payload['att_file']
                
                cur.execute("INSERT INTO messages (sender_id, target_id, target_type, content, timestamp, reply_to_id, attachment_type, attachment_filename, status, forward_from_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (sender, target, payload['type'], payload['text'], str(datetime.now()), payload.get('reply'), payload.get('att_type'), att_fname, 'sent', payload.get('forward_sender_id')))
                msg_id = cur.lastrowid
                db.commit()
                
                if payload['type'] == 'private':
                    utils.broadcast_to_user(payload['target'], {"event": "new_msg", "chat_id": payload['sender'], "type": "private", "att_type": payload.get('att_type'), "att_data": payload.get('att_data'), "sender_id": sender})
                    utils.broadcast_to_user(payload['sender'], {"event": "new_msg", "chat_id": payload['target'], "type": "private", "att_type": payload.get('att_type'), "att_data": payload.get('att_data'), "sender_id": sender})
                else:
                    cur.execute("SELECT user_id FROM group_members WHERE group_id=?", (payload['target'],))
                    for m in cur.fetchall(): utils.broadcast_to_user(m[0], {"event": "new_msg", "chat_id": payload['target'], "type": "group", "att_type": payload.get('att_type'), "att_data": payload.get('att_data'), "sender_id": sender})
                return {"status": "ok", "msg_id": msg_id}
            
            elif action == 'edit_msg':
                cur.execute("SELECT sender_id, target_id, target_type FROM messages WHERE id=?", (payload['msg_id'],))
                res = cur.fetchone()
                if res and res[0] == payload['sender_id']:
                    cur.execute("UPDATE messages SET content=?, is_edited=1 WHERE id=?", (payload['content'], payload['msg_id']))
                    db.commit()
                    if res[2] == 'private':
                         utils.broadcast_to_user(res[1], {"event": "new_msg", "chat_id": res[0], "type": "private"})
                         utils.broadcast_to_user(res[0], {"event": "new_msg", "chat_id": res[1], "type": "private"})
                    else:
                        cur.execute("SELECT user_id FROM group_members WHERE group_id=?", (res[1],))
                        for m in cur.fetchall(): utils.broadcast_to_user(m[0], {"event": "new_msg", "chat_id": res[1], "type": "group"})
                    return {"status": "ok"}
                return {"status": "error"}

            elif action == 'delete_msg':
                cur.execute("SELECT sender_id, target_id, target_type FROM messages WHERE id=?", (payload['msg_id'],))
                res = cur.fetchone()
                if res and res[0] == payload['sender_id']:
                    cur.execute("DELETE FROM messages WHERE id=?", (payload['msg_id'],))
                    cur.execute("DELETE FROM message_reads WHERE message_id=?", (payload['msg_id'],))
                    db.commit()
                    if res[2] == 'private':
                        utils.broadcast_to_user(res[1], {"event": "new_msg", "chat_id": res[0], "type": "private"})
                        utils.broadcast_to_user(res[0], {"event": "new_msg", "chat_id": res[1], "type": "private"})
                    else:
                        cur.execute("SELECT user_id FROM group_members WHERE group_id=?", (res[1],))
                        for m in cur.fetchall(): utils.broadcast_to_user(m[0], {"event": "new_msg", "chat_id": res[1], "type": "group"})
                    return {"status": "ok"}
                return {"status": "error"}

            elif action == 'add_reaction':
                mid, emoji = payload['msg_id'], payload['emoji']
                cur.execute("SELECT reactions, target_id, target_type, sender_id FROM messages WHERE id=?", (mid,))
                curr = cur.fetchone()
                if curr:
                    reacts = json.loads(curr[0])
                    if emoji not in reacts: reacts[emoji] = []
                    if payload['user_id'] not in reacts[emoji]: reacts[emoji].append(payload['user_id'])
                    else:
                        if payload['user_id'] in reacts[emoji]: reacts[emoji].remove(payload['user_id'])
                        if not reacts[emoji]: del reacts[emoji]
                    cur.execute("UPDATE messages SET reactions=? WHERE id=?", (json.dumps(reacts), mid))
                    db.commit()
                    if curr[2] == 'private':
                        p1, p2 = curr[3], curr[1]; utils.broadcast_to_user(p1, {"event": "new_msg", "chat_id": p2, "type": "private"}); utils.broadcast_to_user(p2, {"event": "new_msg", "chat_id": p1, "type": "private"})
                    else:
                        cur.execute("SELECT user_id FROM group_members WHERE group_id=?", (curr[1],))
                        for m in cur.fetchall(): utils.broadcast_to_user(m[0], {"event": "new_msg", "chat_id": curr[1], "type": "group"})
                    return {"status": "ok"}
                return {"status": "error"}

            elif action == 'get_chat':
                my_id, t_id, t_type = payload['my_id'], payload['target_id'], payload['target_type']
                
                is_blocked = False
                if t_type == 'private':
                    cur.execute("SELECT * FROM messages WHERE target_type='private' AND ((sender_id=? AND target_id=?) OR (sender_id=? AND target_id=?))", (my_id, t_id, t_id, my_id))
                    cur2 = db.cursor()
                    cur2.execute("SELECT * FROM user_blocks WHERE user_id=? AND blocked_id=?", (my_id, t_id))
                    if cur2.fetchone(): is_blocked = True
                else:
                    cur.execute("SELECT * FROM messages WHERE target_type='group' AND target_id=?", (t_id,))
                
                msgs = []
                for r in cur.fetchall():
                    # r[1] is sender_id
                    cur.execute("SELECT username, avatar_color, avatar_image, nickname_color, avatar_decoration FROM users WHERE id=?", (r[1],))
                    u = cur.fetchone()
                    
                    # Forward info
                    forward_name, forward_color, forward_img = None, None, None
                    if len(r) > 12 and r[12]: # forward_from_id column
                         cur.execute("SELECT username, avatar_color, avatar_image FROM users WHERE id=?", (r[12],))
                         fu = cur.fetchone()
                         if fu: forward_name, forward_color, forward_img = fu[0], fu[1], fu[2]

                    reply_text = None
                    if r[6]:
                        cur.execute("SELECT username, content, attachment_filename FROM messages m JOIN users u ON m.sender_id=u.id WHERE m.id=?", (r[6],))
                        rep = cur.fetchone()
                        if rep: reply_text = rep[2] if rep[2] else rep[1]

                    read_count = 0
                    if t_type == 'group':
                        cur.execute("SELECT COUNT(*) FROM message_reads WHERE message_id=?", (r[0],))
                        read_count = cur.fetchone()[0]

                    status = 'sent'
                    if len(r) > 11 and r[11]:
                        status = r[11]

                    msgs.append({
                        "id": r[0], "sender_id": r[1], "content": r[4], "time": r[5], "reply_id": r[6], "reply_text": reply_text,
                        "is_edited": r[7], "att_type": r[8], "att_file": r[9], "attachment_filename": r[9],
                        "reactions": json.loads(r[10]) if r[10] else {},
                        "status": status,
                        "read_count": read_count,
                        "sender_name": u[0] if u else "?", "sender_color": u[1] if u else "grey", "sender_image": u[2] if u else None,
                        "nick_color": u[3] if u else "white", "decoration": u[4],
                        "forward_from": forward_name, "forward_sender_color": forward_color, "forward_sender_image": forward_img
                    })
                return {"status": "ok", "messages": msgs, "is_blocked": is_blocked}

            elif action == 'update_profile':
                av_fname = utils.save_file_to_disk(payload['avatar_b64'], "gif" if payload.get('is_gif_av') else "png") if payload.get('avatar_b64') else None
                bn_fname = utils.save_file_to_disk(payload['banner_b64'], "gif" if payload.get('is_gif_bn') else "png") if payload.get('banner_b64') else None
                dec_fname = utils.save_file_to_disk(payload['decor_b64'], "gif") if payload.get('decor_b64') else None
                bg_fname = utils.save_file_to_disk(payload['bg_b64'], "jpg") if payload.get('bg_b64') and payload.get('bg_b64') != 'reset' else None
                
                sql = "UPDATE users SET username=?, about_me=?, banner_color=?, custom_status=?, nickname_color=?"
                params = [payload['username'], payload['about'], payload['banner'], payload['custom_status'], payload['nickname_color']]
                if av_fname: sql += ", avatar_image=?"; params.append(av_fname)
                if bn_fname: sql += ", banner_image=?"; params.append(bn_fname)
                if dec_fname: sql += ", avatar_decoration=?"; params.append(dec_fname)
                if bg_fname: sql += ", chat_bg=?"; params.append(bg_fname)
                elif payload.get('bg_b64') == 'reset': sql += ", chat_bg=?"; params.append(None)
                
                sql += " WHERE id=?"; params.append(payload['id'])
                cur.execute(sql, params); db.commit()
                utils.broadcast_all({"event": "profile_updated", "user_id": payload['id']})
                return {"status": "ok", "new_avatar": av_fname, "new_banner": bn_fname, "new_decor": dec_fname, "new_bg": bg_fname}

            elif action == 'admin_get_all_users':
                cur.execute("SELECT id, username, discriminator, email, is_blocked, is_admin FROM users")
                return {"status": "ok", "users": [{"id":r[0], "tag":f"{r[1]}#{r[2]}", "email":r[3], "blocked":r[4], "is_admin":r[5]} for r in cur.fetchall()]}
            elif action == 'admin_ban_user':
                cur.execute("UPDATE users SET is_blocked=1, ban_reason=? WHERE id=?", (payload.get('reason', 'Нарушение правил'), payload['target_id']))
                db.commit(); return {"status": "ok"}
            elif action == 'admin_unban_user':
                cur.execute("UPDATE users SET is_blocked=0 WHERE id=?", (payload['target_id'],)); db.commit(); return {"status": "ok"}
            elif action == 'admin_broadcast_msg':
                target_id = payload.get('target_id')
                text = payload['text']
                if target_id is not None:
                    cur.execute("INSERT INTO messages (sender_id, target_id, target_type, content, timestamp, status) VALUES (0, ?, 'private', ?, ?, 'sent')",
                                (target_id, text, str(datetime.now())))
                    db.commit()
                    utils.broadcast_to_user(target_id, {"event": "new_msg", "chat_id": 0, "type": "private"})
                else:
                    cur.execute("SELECT id FROM users WHERE id != 0")
                    users = cur.fetchall()
                    for u in users:
                        cur.execute("INSERT INTO messages (sender_id, target_id, target_type, content, timestamp, status) VALUES (0, ?, 'private', ?, ?, 'sent')",
                                    (u[0], text, str(datetime.now())))
                        utils.broadcast_to_user(u[0], {"event": "new_msg", "chat_id": 0, "type": "private"})
                    db.commit()
                return {"status": "ok"}
            elif action == 'admin_add_units':
                cur.execute("UPDATE users SET units = units + ? WHERE id=?", (payload['amount'], payload['target_id']))
                db.commit()
                utils.broadcast_to_user(payload['target_id'], {"event": "profile_updated", "user_id": payload['target_id']})
                return {"status": "ok"}
            
            elif action == 'get_mutual_info':
                return {"status": "ok", "mutual_friends": [], "mutual_groups": []}
            
            elif action == 'update_profile_music':
                uid, track_src, track_name = payload['user_id'], payload['track_src'], payload['track_name']
                music_data = json.dumps({"src": track_src, "name": track_name})
                cur.execute("UPDATE users SET profile_music=? WHERE id=?", (music_data, uid))
                db.commit()
                utils.broadcast_all({"event": "profile_updated", "user_id": uid})
                return {"status": "ok"}

            elif action == 'mark_messages_read':
                user_id = payload['user_id']
                chat_id = payload['chat_id']
                chat_type = payload['chat_type']
                if chat_type == 'private':
                    cur.execute("SELECT id FROM messages WHERE target_type='private' AND sender_id=? AND target_id=? AND status != 'read'", (chat_id, user_id))
                else:
                    cur.execute("SELECT id FROM messages WHERE target_type='group' AND target_id=? AND sender_id != ?", (chat_id, user_id))
                msg_ids = [r[0] for r in cur.fetchall()]
                for mid in msg_ids:
                    cur.execute("INSERT OR IGNORE INTO message_reads (message_id, user_id, read_at) VALUES (?,?,?)", (mid, user_id, str(datetime.now())))
                    if chat_type == 'private': cur.execute("UPDATE messages SET status='read' WHERE id=?", (mid,))
                db.commit()
                if chat_type == 'private' and msg_ids:
                    utils.broadcast_to_user(chat_id, {"event": "messages_read", "chat_id": user_id, "type": "private"})
                return {"status": "ok"}

            elif action == 'get_message_readers':
                msg_id = payload['message_id']
                cur.execute("SELECT u.id, u.username, u.discriminator, u.avatar_color, u.avatar_image, mr.read_at FROM message_reads mr JOIN users u ON mr.user_id = u.id WHERE mr.message_id = ?", (msg_id,))
                readers = [{"id": r[0], "username": r[1], "tag": r[2], "color": r[3], "image": r[4], "read_at": r[5]} for r in cur.fetchall()]
                return {"status": "ok", "readers": readers}

        except Exception as e: 
            import traceback
            traceback.print_exc()
            return {"status": "error", "msg": str(e)}
        finally: db.close()
    return {"status": "error"}