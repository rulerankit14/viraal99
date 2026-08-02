#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
VIRAL 99 Telegram Bot - Full Admin Panel
Premium Content Access Bot with Extended Admin Dashboard

Features:
- Age verification (18+)
- Premium plan selection (4 tiers)
- Payment processing with UPI/QR
- Referral system with discounts
- FULL ADMIN PANEL with:
  • Statistics
  • Welcome Text (customizable)
  • Demo Link
  • Manage Plans (edit prices/durations)
  • Pending Payments (verify/reject)
  • Broadcast
  • VIP Users
  • Coupons (generate & manage)
  • Suspicious Users (flag users)
  • Manual Pay (mark user paid)
  • Transfer Ownership (placeholder)
  • User List (export)
  • DB Backup
  • Demo Bot Token (show token)
  • Backup Channel (set)
  • Tutorial Video (set)
  • Refresh Cache
  • Reset Revenue/Stats
  • Lock Admin Panel (password)
  • CLONE THIS BOT (info)

Tech: python-telegram-bot v20+, SQLite, asyncio
"""

import os
import json
import sqlite3
import logging
import asyncio
import random
import string
import csv
from io import StringIO
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    CallbackQuery, Message, User, Chat
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)
from telegram.constants import ParseMode

# ==================== CONFIGURATION ====================

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
ADMIN_IDS = [int(id) for id in os.getenv("ADMIN_IDS", "123456789").split(",")]
DATABASE_FILE = "viral99.db"
REFERRAL_DISCOUNT = 10  # Percentage discount for referrals

# Plan configurations (will be stored in DB eventually)
DEFAULT_PLANS = {
    "STANDARD": {"price": 99, "label": "STANDARD", "duration": "1 Month", "emoji": "📱"},
    "VIP": {"price": 149, "label": "VIP", "duration": "3 Months", "emoji": "⭐"},
    "CZF": {"price": 199, "label": "CZF", "duration": "6 Months", "emoji": "👑"},
    "KAMASUTRA": {"price": 999, "label": "KAMASUTRA", "duration": "Lifetime", "emoji": "💎"},
}

# ==================== LOGGING ====================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== DATABASE ====================

@contextmanager
def get_db():
    """Database connection context manager"""
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Database error: {e}")
        raise
    finally:
        conn.close()


def init_database():
    """Initialize database tables"""
    with get_db() as conn:
        cursor = conn.cursor()

        # Users table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                age_verified INTEGER DEFAULT 0,
                plan TEXT,
                plan_expiry TEXT,
                payment_status TEXT DEFAULT 'pending',
                referral_code TEXT UNIQUE,
                referred_by INTEGER,
                join_date TEXT DEFAULT CURRENT_TIMESTAMP,
                last_active TEXT DEFAULT CURRENT_TIMESTAMP,
                is_active INTEGER DEFAULT 1,
                is_suspicious INTEGER DEFAULT 0,
                suspension_reason TEXT
            )
        """)

        # Payments table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                plan TEXT,
                amount INTEGER,
                transaction_id TEXT,
                payment_proof TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                verified_at TEXT,
                verified_by INTEGER,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        """)

        # Referrals table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER,
                referred_id INTEGER,
                referred_at TEXT DEFAULT CURRENT_TIMESTAMP,
                reward_claimed INTEGER DEFAULT 0,
                FOREIGN KEY (referrer_id) REFERENCES users (user_id),
                FOREIGN KEY (referred_id) REFERENCES users (user_id)
            )
        """)

        # Admin logs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS admin_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER,
                action TEXT,
                details TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Broadcasts table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS broadcasts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER,
                message TEXT,
                recipients INTEGER,
                sent_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Settings table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Coupons table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS coupons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE,
                discount_percent INTEGER,
                expiry TEXT,
                max_uses INTEGER DEFAULT 1,
                used_count INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                is_active INTEGER DEFAULT 1
            )
        """)

        # Plans table (for dynamic plans)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE,
                label TEXT,
                price INTEGER,
                duration TEXT,
                emoji TEXT,
                is_active INTEGER DEFAULT 1
            )
        """)

        # Insert default plans if not exist
        for key, plan in DEFAULT_PLANS.items():
            cursor.execute(
                "INSERT OR IGNORE INTO plans (key, label, price, duration, emoji) VALUES (?, ?, ?, ?, ?)",
                (key, plan["label"], plan["price"], plan["duration"], plan["emoji"])
            )

        # Insert default settings
        default_settings = {
            "welcome_text": "Welcome to VIRAL 99! Enjoy premium content.",
            "demo_link": "https://t.me/viral99_demo",
            "backup_channel": "",
            "tutorial_video": "",
            "admin_password": "",  # empty means no password
            "is_admin_locked": "0",
        }
        for key, value in default_settings.items():
            cursor.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (key, value)
            )

        # Generate referral codes for existing users if missing
        cursor.execute("SELECT user_id FROM users WHERE referral_code IS NULL")
        users_without_code = cursor.fetchall()
        for user in users_without_code:
            code = generate_referral_code()
            cursor.execute(
                "UPDATE users SET referral_code = ? WHERE user_id = ?",
                (code, user["user_id"])
            )


def get_setting(key: str) -> Optional[str]:
    """Get a setting value"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row["value"] if row else None


def set_setting(key: str, value: str) -> None:
    """Set a setting value"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
            (key, value)
        )


def get_all_plans() -> List[Dict]:
    """Get all active plans from DB"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM plans WHERE is_active = 1 ORDER BY price")
        return [dict(row) for row in cursor.fetchall()]


def update_plan(key: str, **kwargs) -> None:
    """Update plan fields"""
    with get_db() as conn:
        cursor = conn.cursor()
        fields = []
        values = []
        for k, v in kwargs.items():
            fields.append(f"{k} = ?")
            values.append(v)
        values.append(key)
        cursor.execute(
            f"UPDATE plans SET {', '.join(fields)} WHERE key = ?",
            values
        )


def generate_referral_code(length: int = 6) -> str:
    """Generate a unique referral code"""
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choices(chars, k=length))


def get_user(user_id: int) -> Optional[Dict]:
    """Get user from database"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def create_user(user_id: int, username: str = None, first_name: str = None,
                last_name: str = None, referred_by: int = None) -> Dict:
    """Create a new user"""
    with get_db() as conn:
        cursor = conn.cursor()

        # Check if user exists
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        existing = cursor.fetchone()
        if existing:
            return dict(existing)

        # Generate referral code
        referral_code = generate_referral_code()

        cursor.execute("""
            INSERT INTO users (user_id, username, first_name, last_name, referral_code, referred_by)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, username, first_name, last_name, referral_code, referred_by))

        # Record referral if applicable
        if referred_by:
            cursor.execute("""
                INSERT INTO referrals (referrer_id, referred_id)
                VALUES (?, ?)
            """, (referred_by, user_id))

        cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return dict(cursor.fetchone())


def update_user(user_id: int, **kwargs) -> None:
    """Update user fields"""
    with get_db() as conn:
        cursor = conn.cursor()
        fields = []
        values = []
        for key, value in kwargs.items():
            fields.append(f"{key} = ?")
            values.append(value)
        values.append(user_id)
        cursor.execute(
            f"UPDATE users SET {', '.join(fields)} WHERE user_id = ?",
            values
        )


def get_user_by_referral_code(code: str) -> Optional[Dict]:
    """Get user by referral code"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE referral_code = ?", (code,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_pending_payments() -> List[Dict]:
    """Get all pending payments"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT p.*, u.username, u.first_name
            FROM payments p
            JOIN users u ON p.user_id = u.user_id
            WHERE p.status = 'pending'
            ORDER BY p.created_at DESC
        """)
        return [dict(row) for row in cursor.fetchall()]


def get_all_users(include_suspicious: bool = False) -> List[Dict]:
    """Get all users"""
    with get_db() as conn:
        cursor = conn.cursor()
        if include_suspicious:
            cursor.execute("SELECT * FROM users ORDER BY join_date DESC")
        else:
            cursor.execute("SELECT * FROM users WHERE is_suspicious = 0 ORDER BY join_date DESC")
        return [dict(row) for row in cursor.fetchall()]


def get_vip_users() -> List[Dict]:
    """Get users with active paid plans"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM users
            WHERE payment_status = 'confirmed'
            AND plan IS NOT NULL
            AND plan_expiry > datetime('now')
            ORDER BY join_date DESC
        """)
        return [dict(row) for row in cursor.fetchall()]


def get_suspicious_users() -> List[Dict]:
    """Get suspicious users"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE is_suspicious = 1 ORDER BY join_date DESC")
        return [dict(row) for row in cursor.fetchall()]


def mark_user_suspicious(user_id: int, reason: str = "") -> None:
    """Mark a user as suspicious"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET is_suspicious = 1, suspension_reason = ? WHERE user_id = ?",
            (reason, user_id)
        )


def mark_user_unsuspicious(user_id: int) -> None:
    """Remove suspicious flag"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET is_suspicious = 0, suspension_reason = NULL WHERE user_id = ?",
            (user_id,)
        )


def get_stats() -> Dict:
    """Get bot statistics"""
    with get_db() as conn:
        cursor = conn.cursor()

        # Total users
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]

        # Active users (last 30 days)
        cursor.execute("""
            SELECT COUNT(*) FROM users
            WHERE last_active > datetime('now', '-30 days')
        """)
        active_users = cursor.fetchone()[0]

        # Active today
        cursor.execute("""
            SELECT COUNT(*) FROM users
            WHERE last_active > datetime('now', 'start of day')
        """)
        active_today = cursor.fetchone()[0]

        # Age verified
        cursor.execute("SELECT COUNT(*) FROM users WHERE age_verified = 1")
        age_verified = cursor.fetchone()[0]

        # Paid users
        cursor.execute("SELECT COUNT(*) FROM users WHERE payment_status = 'confirmed' AND plan_expiry > datetime('now')")
        paid_users = cursor.fetchone()[0]

        # Total revenue
        cursor.execute("SELECT SUM(amount) FROM payments WHERE status = 'confirmed'")
        total_revenue = cursor.fetchone()[0] or 0

        # Pending payments
        cursor.execute("SELECT COUNT(*) FROM payments WHERE status = 'pending'")
        pending_payments = cursor.fetchone()[0]

        # Total referrals
        cursor.execute("SELECT COUNT(*) FROM referrals")
        total_referrals = cursor.fetchone()[0]

        # Suspicious users
        cursor.execute("SELECT COUNT(*) FROM users WHERE is_suspicious = 1")
        suspicious_users = cursor.fetchone()[0]

        return {
            "total_users": total_users,
            "active_users": active_users,
            "active_today": active_today,
            "age_verified": age_verified,
            "paid_users": paid_users,
            "total_revenue": total_revenue,
            "pending_payments": pending_payments,
            "total_referrals": total_referrals,
            "suspicious_users": suspicious_users,
        }


def add_payment(user_id: int, plan: str, amount: int, transaction_id: str = None) -> int:
    """Add a payment record"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO payments (user_id, plan, amount, transaction_id, status)
            VALUES (?, ?, ?, ?, 'pending')
        """, (user_id, plan, amount, transaction_id))
        payment_id = cursor.lastrowid

        # Update user payment status
        cursor.execute("""
            UPDATE users SET payment_status = 'pending'
            WHERE user_id = ?
        """, (user_id,))

        return payment_id


def verify_payment(payment_id: int, admin_id: int) -> bool:
    """Verify a payment"""
    with get_db() as conn:
        cursor = conn.cursor()

        # Get payment details
        cursor.execute("SELECT * FROM payments WHERE id = ?", (payment_id,))
        payment = cursor.fetchone()
        if not payment:
            return False

        # Update payment status
        cursor.execute("""
            UPDATE payments
            SET status = 'confirmed', verified_at = CURRENT_TIMESTAMP, verified_by = ?
            WHERE id = ?
        """, (admin_id, payment_id))

        # Update user payment status and plan
        user_id = payment["user_id"]
        plan = payment["plan"]

        # Get plan duration from plans table
        cursor.execute("SELECT duration FROM plans WHERE key = ?", (plan,))
        plan_row = cursor.fetchone()
        duration_days = 30  # default
        if plan_row:
            dur_str = plan_row["duration"]
            if "Month" in dur_str:
                months = int(dur_str.split()[0]) if dur_str.split()[0].isdigit() else 1
                duration_days = months * 30
            elif "Year" in dur_str:
                years = int(dur_str.split()[0]) if dur_str.split()[0].isdigit() else 1
                duration_days = years * 365
            elif "Lifetime" in dur_str:
                duration_days = 365 * 10  # 10 years

        expiry = (datetime.now() + timedelta(days=duration_days)).isoformat()

        cursor.execute("""
            UPDATE users
            SET plan = ?, plan_expiry = ?, payment_status = 'confirmed'
            WHERE user_id = ?
        """, (plan, expiry, user_id))

        return True


def reject_payment(payment_id: int, admin_id: int) -> bool:
    """Reject a payment"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE payments
            SET status = 'rejected', verified_at = CURRENT_TIMESTAMP, verified_by = ?
            WHERE id = ?
        """, (admin_id, payment_id))

        cursor.execute("""
            UPDATE users
            SET payment_status = 'rejected'
            WHERE user_id = (SELECT user_id FROM payments WHERE id = ?)
        """, (payment_id,))

        return True


def manual_pay_user(user_id: int, plan: str, admin_id: int) -> bool:
    """Manually mark user as paid"""
    with get_db() as conn:
        cursor = conn.cursor()

        # Check if user exists
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        if not cursor.fetchone():
            return False

        # Get plan duration
        cursor.execute("SELECT duration FROM plans WHERE key = ?", (plan,))
        plan_row = cursor.fetchone()
        duration_days = 30
        if plan_row:
            dur_str = plan_row["duration"]
            if "Month" in dur_str:
                months = int(dur_str.split()[0]) if dur_str.split()[0].isdigit() else 1
                duration_days = months * 30
            elif "Year" in dur_str:
                years = int(dur_str.split()[0]) if dur_str.split()[0].isdigit() else 1
                duration_days = years * 365
            elif "Lifetime" in dur_str:
                duration_days = 365 * 10

        expiry = (datetime.now() + timedelta(days=duration_days)).isoformat()

        cursor.execute("""
            UPDATE users
            SET plan = ?, plan_expiry = ?, payment_status = 'confirmed'
            WHERE user_id = ?
        """, (plan, expiry, user_id))

        # Insert a dummy payment record
        cursor.execute("""
            INSERT INTO payments (user_id, plan, amount, status, verified_at, verified_by)
            VALUES (?, ?, 0, 'confirmed', CURRENT_TIMESTAMP, ?)
        """, (user_id, plan, admin_id))

        log_admin_action(admin_id, "manual_pay", f"User {user_id} marked as paid for {plan}")
        return True


def log_admin_action(admin_id: int, action: str, details: str = "") -> None:
    """Log admin action"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO admin_logs (admin_id, action, details)
            VALUES (?, ?, ?)
        """, (admin_id, action, details))


def get_referral_stats(user_id: int) -> Dict:
    """Get referral stats for a user"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) as total, COUNT(CASE WHEN reward_claimed = 1 THEN 1 END) as claimed
            FROM referrals
            WHERE referrer_id = ?
        """, (user_id,))
        row = cursor.fetchone()
        return {"total": row[0], "claimed": row[1]}


def generate_coupon(discount: int, max_uses: int = 1, expiry_days: int = 30) -> str:
    """Generate a unique coupon code"""
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    expiry = (datetime.now() + timedelta(days=expiry_days)).isoformat()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO coupons (code, discount_percent, expiry, max_uses)
            VALUES (?, ?, ?, ?)
        """, (code, discount, expiry, max_uses))
    return code


def get_all_coupons() -> List[Dict]:
    """Get all coupons"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM coupons ORDER BY created_at DESC")
        return [dict(row) for row in cursor.fetchall()]


def apply_coupon(code: str) -> Optional[int]:
    """Apply coupon and return discount percent if valid"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM coupons
            WHERE code = ? AND is_active = 1
            AND expiry > datetime('now')
            AND used_count < max_uses
        """, (code,))
        coupon = cursor.fetchone()
        if not coupon:
            return None
        # Increment used count
        cursor.execute(
            "UPDATE coupons SET used_count = used_count + 1 WHERE code = ?",
            (code,)
        )
        return coupon["discount_percent"]


# ==================== BOT HANDLERS ====================

# Conversation states
AGE_VERIFICATION, PLAN_SELECTION, PAYMENT, PAYMENT_PROOF, ADMIN_MANUAL_PAY, ADMIN_EDIT_PLAN = range(6)


# ===== USER COMMANDS =====

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /start command"""
    user = update.effective_user
    referred_by = None

    # Check if there's a referral code in the command
    if context.args:
        ref_code = context.args[0]
        referrer = get_user_by_referral_code(ref_code)
        if referrer and referrer["user_id"] != user.id:
            referred_by = referrer["user_id"]

    # Create or get user
    db_user = create_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        referred_by=referred_by
    )

    # Update last active
    update_user(user.id, last_active=datetime.now().isoformat())

    # Get stats for display
    stats = get_stats()
    welcome_text = get_setting("welcome_text") or "Welcome to VIRAL 99!"

    welcome_msg = (
        f"👋 {welcome_text}\n\n"
        f"🎬 *4,50,000+ Premium HD Videos* – Sab Ek Hi Jagah ✅\n"
        f"• Lifetime Collection ✅\n"
        f"• Daily Updates ✅\n"
        f"• HD Quality ✅\n"
        f"• No Blur, No Low Quality ✅\n"
        f"• Na Ads ✅\n"
        f"• Na Redirect Links ✅\n"
        f"• Payment ke sirf 15 Minutes ke andar Access ✅\n"
        f"• 100% Private & secure ✅\n\n"
        f"👥 {stats['total_users']:,} users already joined\n"
        f"📊 {stats['active_users']:,} active this month · {stats['active_today']} active today\n\n"
        f"👇 *BUY PREMIUM ACCESS* par tap karo aur turant access lo ❤️"
    )

    keyboard = [
        [InlineKeyboardButton("🔥 BUY PREMIUM ACCESS", callback_data="buy_premium")],
        [InlineKeyboardButton("🎬 FREE DEMO", callback_data="free_demo"),
         InlineKeyboardButton("📸 PROOFS", callback_data="proofs")],
        [InlineKeyboardButton("👤 MY PROFILE", callback_data="my_profile"),
         InlineKeyboardButton("🆘 SUPPORT", callback_data="support")],
        [InlineKeyboardButton("📌 MORE OPTIONS", callback_data="more_options")],
    ]

    await update.message.reply_text(
        welcome_msg,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

    return ConversationHandler.END


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle callback queries from inline keyboards"""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data = query.data

    # Update last active
    update_user(user_id, last_active=datetime.now().isoformat())

    if data == "buy_premium":
        # Check if user is age verified
        db_user = get_user(user_id)
        if not db_user or not db_user.get("age_verified"):
            await age_verification_prompt(query)
            return

        # Check if user already has active plan
        if db_user.get("payment_status") == "confirmed" and db_user.get("plan_expiry"):
            expiry = datetime.fromisoformat(db_user["plan_expiry"])
            if expiry > datetime.now():
                await query.edit_message_text(
                    f"✅ *Aapke paas already active plan hai!*\n\n"
                    f"📋 Plan: *{db_user['plan']}*\n"
                    f"⏳ Expiry: *{expiry.strftime('%d %b %Y')}*\n\n"
                    f"Kya aap naya plan lena chahte hain?",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 Renew Plan", callback_data="renew_plan")],
                        [InlineKeyboardButton("🔙 Wapas jao", callback_data="back_to_start")]
                    ])
                )
                return

        await show_plans(query)

    elif data == "renew_plan":
        await show_plans(query)

    elif data == "free_demo":
        demo_link = get_setting("demo_link") or "https://t.me/viral99_demo"
        await query.edit_message_text(
            f"🎬 *FREE DEMO*\n\n"
            f"Yahan aap premium content ka sample dekh sakte hain.\n\n"
            f"🔗 Demo Link: {demo_link}\n\n"
            f"⚠️ Demo version mein limited content hai.\n"
            f"Full access ke liye *BUY PREMIUM ACCESS* karein!",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Wapas jao", callback_data="back_to_start")]
            ])
        )

    elif data == "proofs":
        await query.edit_message_text(
            "📸 *PROOFS*\n\n"
            "✅ 10,000+ satisfied users\n"
            "✅ 4.9/5 rating\n"
            "✅ 99.9% uptime\n"
            "✅ Fast delivery within 15 minutes\n\n"
            "Check karein humare telegram channel par!",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Wapas jao", callback_data="back_to_start")]
            ])
        )

    elif data == "my_profile":
        await show_profile(query)

    elif data == "support":
        await query.edit_message_text(
            "🆘 *SUPPORT*\n\n"
            "Koi bhi issue ho toh humse contact karein:\n\n"
            "📧 Email: support@viral99.com\n"
            "📱 Telegram: @viral99_support\n"
            "⏰ Response Time: 5-30 minutes\n\n"
            "Hum 24/7 available hain!",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Wapas jao", callback_data="back_to_start")]
            ])
        )

    elif data == "more_options":
        await query.edit_message_text(
            "📌 *MORE OPTIONS*\n\n"
            "Select an option:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 FAQ", callback_data="faq")],
                [InlineKeyboardButton("📢 Refer & Earn", callback_data="refer_earn")],
                [InlineKeyboardButton("📊 Status", callback_data="status")],
                [InlineKeyboardButton("🔙 Wapas jao", callback_data="back_to_start")]
            ])
        )

    elif data == "faq":
        await query.edit_message_text(
            "📋 *FAQ – Aksar Puche Gaye Sawaal*\n\n"
            "❓ *Payment ke baad kitni der mein access milega?*\n"
            "➡️ 15 minutes ke andar access mil jaata hai.\n\n"
            "❓ *Kya refund possible hai?*\n"
            "➡️ Nahi, refund nahi hota. Quality guaranteed hai.\n\n"
            "❓ *Kitne devices par use kar sakte hain?*\n"
            "➡️ Unlimited devices par use kar sakte hain.\n\n"
            "❓ *Kya content daily update hota hai?*\n"
            "➡️ Haan, rozana naye videos add hote hain.\n\n"
            "❓ *Kya payment secure hai?*\n"
            "➡️ 100% secure, humara koi data store nahi hota.\n\n"
            "❓ *Referral kaise kaam karta hai?*\n"
            "➡️ Apna referral code share karein, har successful referral par 10% discount.\n\n"
            "🔙 *Wapas jao*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Wapas jao", callback_data="more_options")]
            ])
        )

    elif data == "refer_earn":
        db_user = get_user(user_id)
        ref_code = db_user.get("referral_code", "")
        ref_stats = get_referral_stats(user_id)

        await query.edit_message_text(
            f"📢 *Refer & Earn*\n\n"
            f"Apna referral code share karein aur har successful referral par *{REFERRAL_DISCOUNT}% discount* paayein!\n\n"
            f"🔑 *Aapka Referral Code:* `{ref_code}`\n\n"
            f"📊 Total Referrals: {ref_stats['total']}\n"
            f"✅ Claimed: {ref_stats['claimed']}\n\n"
            f"Share karein: https://t.me/{(await context.bot.get_me()).username}?start={ref_code}\n\n"
            f"💡 *Tip:* Jitne zyada referrals, utna zyada discount!",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📤 Share Referral Link", callback_data="share_ref")],
                [InlineKeyboardButton("🔙 Wapas jao", callback_data="more_options")]
            ])
        )

    elif data == "share_ref":
        db_user = get_user(user_id)
        ref_code = db_user.get("referral_code", "")
        bot_username = (await context.bot.get_me()).username

        await query.edit_message_text(
            f"📤 *Share Referral Link*\n\n"
            f"Copy karein aur share karein:\n\n"
            f"`https://t.me/{bot_username}?start={ref_code}`\n\n"
            f"Ya direct message karein:\n\n"
            f"\"Join VIRAL 99 with my referral link and get premium access!\"",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Wapas jao", callback_data="refer_earn")]
            ])
        )

    elif data == "status":
        db_user = get_user(user_id)
        stats = get_stats()

        status_text = (
            f"📊 *VIRAL 99 Status*\n\n"
            f"👥 Total Users: *{stats['total_users']:,}*\n"
            f"📅 Active (30 days): *{stats['active_users']:,}*\n"
            f"📆 Active Today: *{stats['active_today']}*\n"
            f"✅ Age Verified: *{stats['age_verified']:,}*\n"
            f"💎 Paid Users: *{stats['paid_users']:,}*\n"
            f"💰 Revenue: *₹{stats['total_revenue']:,}*\n"
            f"⏳ Pending Payments: *{stats['pending_payments']}*\n"
            f"🔗 Total Referrals: *{stats['total_referrals']}*\n\n"
            f"📌 *Your Status*\n"
            f"👤 User ID: `{user_id}`\n"
            f"📋 Plan: *{db_user.get('plan') or 'None'}*\n"
            f"💳 Payment: *{db_user.get('payment_status') or 'pending'}*"
        )

        await query.edit_message_text(
            status_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Refresh", callback_data="status")],
                [InlineKeyboardButton("🔙 Wapas jao", callback_data="more_options")]
            ])
        )

    elif data == "back_to_start":
        await start_callback(query)


async def age_verification_prompt(query: CallbackQuery) -> None:
    """Prompt user for age verification"""
    await query.edit_message_text(
        "⚠️ *Quick Verification*\n\n"
        "Confirm karo — tumhari umar 18+ hai?\n"
        "(Yeh sirf ek baar poochha jaayeega)",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Haan, mai 18+ hoon — Enter karo", callback_data="age_yes")],
            [InlineKeyboardButton("❌ Nahi, mai 18 se kam hoon", callback_data="age_no")]
        ])
    )


async def age_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle age verification callback"""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data = query.data

    if data == "age_yes":
        # Update user age verification
        update_user(user_id, age_verified=1)
        await show_plans(query)

    elif data == "age_no":
        await query.edit_message_text(
            "❌ *Access Denied*\n\n"
            "Yeh content sirf 18+ ke liye hai.\n"
            "Aap is bot ko use nahi kar sakte.",
            parse_mode=ParseMode.MARKDOWN
        )


async def show_plans(query: CallbackQuery) -> None:
    """Show available plans"""
    # Get user for referral discount
    db_user = get_user(query.from_user.id)
    ref_stats = get_referral_stats(query.from_user.id)

    discount = min(ref_stats['total'] * REFERRAL_DISCOUNT, 50)  # Max 50% discount

    plan_text = "💎 *PLAN CHUNO*\n\n"
    plan_text += "Jitne zyada din — utna sasta!\n"
    plan_text += "Ek tap mein select karo:\n\n"

    plans = get_all_plans()
    keyboard = []

    for plan in plans:
        key = plan["key"]
        price = plan["price"]
        label = plan["label"]
        duration = plan["duration"]
        emoji = plan["emoji"]

        if discount > 0:
            discounted_price = price - int(price * discount / 100)
            plan_text += f"{emoji} *{label}* — ₹{discounted_price} (₹{price} → {discount}% OFF)\n"
            keyboard.append([InlineKeyboardButton(
                f"{emoji} ₹{discounted_price} {label} ({duration})",
                callback_data=f"plan_{key}_{discounted_price}"
            )])
        else:
            plan_text += f"{emoji} *{label}* — ₹{price} ({duration})\n"
            keyboard.append([InlineKeyboardButton(
                f"{emoji} ₹{price} {label} ({duration})",
                callback_data=f"plan_{key}_{price}"
            )])

    if discount > 0:
        plan_text += f"\n🎉 *{discount}% discount applied!* (Referral bonus)"

    plan_text += "\n\n🔙 Wapas jao"

    keyboard.append([InlineKeyboardButton("🔙 Wapas jao", callback_data="back_to_start")])

    await query.edit_message_text(
        plan_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def plan_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle plan selection callback"""
    query = update.callback_query
    await query.answer()

    data = query.data
    _, plan_key, price = data.split("_")
    price = int(price)

    user_id = query.from_user.id

    # Store selected plan in context
    context.user_data["selected_plan"] = plan_key
    context.user_data["selected_price"] = price

    # Generate UPI payment instructions
    upi_id = "viral99@upi"  # Replace with actual UPI ID

    payment_text = (
        f"💳 *Payment Instructions*\n\n"
        f"📋 Plan: *{plan_key}*\n"
        f"💰 Amount: *₹{price}*\n\n"
        f"🔹 *UPI Payment*\n"
        f"Pay to: `{upi_id}`\n\n"
        f"🔹 *QR Code*\n"
        f"(Attach QR code image here or use UPI)\n\n"
        f"⚠️ *Important:*\n"
        f"• Payment ke baad transaction ID bhejein\n"
        f"• Screenshot bhi bhej sakte hain\n"
        f"• 15 minutes mein access mil jaayega\n\n"
        f"✅ *Payment karne ke baad 'Payment Done' button dabayein*"
    )

    keyboard = [
        [InlineKeyboardButton("✅ Payment Done", callback_data="payment_done")],
        [InlineKeyboardButton("🔄 Different Plan", callback_data="buy_premium")],
        [InlineKeyboardButton("🔙 Wapas jao", callback_data="back_to_start")]
    ]

    await query.edit_message_text(
        payment_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def payment_done_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle payment done callback"""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    # Get selected plan from context
    plan_key = context.user_data.get("selected_plan")
    price = context.user_data.get("selected_price")

    if not plan_key or not price:
        await query.edit_message_text(
            "❌ *Error*\n\n"
            "Koi plan select nahi kiya gaya. Please try again.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Select Plan", callback_data="buy_premium")]
            ])
        )
        return

    # Add payment record
    payment_id = add_payment(user_id, plan_key, price)

    # Store payment ID in context
    context.user_data["payment_id"] = payment_id

    await query.edit_message_text(
        f"📤 *Payment Confirmation*\n\n"
        f"Plan: *{plan_key}*\n"
        f"Amount: *₹{price}*\n"
        f"Payment ID: `{payment_id}`\n\n"
        f"🔹 *Please send your payment screenshot or transaction ID*\n"
        f"🔹 Type /cancel to cancel\n\n"
        f"⏳ Admin verify karega aur 15 minutes mein access mil jaayega!",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📤 Send Payment Proof", callback_data="send_proof")],
            [InlineKeyboardButton("🔙 Wapas jao", callback_data="back_to_start")]
        ])
    )


async def send_proof_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle send proof callback"""
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "📤 *Send Payment Proof*\n\n"
        "Please send:\n"
        "1. 📸 Payment screenshot (UPI/GPay/PhonePe)\n"
        "2. 🔢 Transaction ID\n\n"
        "Ya dono bhej sakte hain.\n\n"
        "⏳ Admin verify karega aur 15 minutes mein access denge!",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Wapas jao", callback_data="back_to_start")]
        ])
    )

    return PAYMENT_PROOF


async def handle_payment_proof(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle payment proof message (photo or text)"""
    user_id = update.effective_user.id
    message = update.message

    # Get payment ID from context
    payment_id = context.user_data.get("payment_id")
    if not payment_id:
        await message.reply_text(
            "❌ *Error*\n\n"
            "Payment session expired. Please start over.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Start Over", callback_data="back_to_start")]
            ])
        )
        return ConversationHandler.END

    # Store proof
    proof_text = ""
    if message.photo:
        # Get the largest photo
        photo = message.photo[-1]
        file_id = photo.file_id
        proof_text = f"Photo: {file_id}"
    elif message.text:
        proof_text = message.text
    else:
        await message.reply_text(
            "❌ Please send a photo or text as payment proof.",
            parse_mode=ParseMode.MARKDOWN
        )
        return PAYMENT_PROOF

    # Update payment with proof
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE payments SET payment_proof = ? WHERE id = ?",
            (proof_text, payment_id)
        )

    # Notify admin
    admin_message = (
        f"📢 *New Payment Proof Received!*\n\n"
        f"👤 User: {update.effective_user.first_name} (@{update.effective_user.username or 'N/A'})\n"
        f"🆔 User ID: `{user_id}`\n"
        f"💳 Payment ID: `{payment_id}`\n"
        f"📝 Proof: {proof_text[:200]}...\n\n"
        f"Use /admin to manage."
    )

    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                admin_id,
                admin_message,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📋 Go to Admin Panel", callback_data="admin_panel")]
                ])
            )
        except Exception as e:
            logger.error(f"Failed to notify admin {admin_id}: {e}")

    # Confirm to user
    await message.reply_text(
        f"✅ *Payment Proof Received!*\n\n"
        f"Payment ID: `{payment_id}`\n\n"
        f"⏳ Admin verify kar raha hai...\n"
        f"📱 15 minutes mein access mil jaayega!\n\n"
        f"Thank you for choosing VIRAL 99! ❤️",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 Check Status", callback_data="status")],
            [InlineKeyboardButton("🔙 Home", callback_data="back_to_start")]
        ])
    )

    return ConversationHandler.END


async def show_profile(query: CallbackQuery) -> None:
    """Show user profile"""
    user_id = query.from_user.id
    db_user = get_user(user_id)

    if not db_user:
        await query.edit_message_text(
            "❌ User not found. Please /start again.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # Get referral stats
    ref_stats = get_referral_stats(user_id)

    plan = db_user.get("plan") or "None"
    expiry = db_user.get("plan_expiry")
    if expiry:
        expiry_dt = datetime.fromisoformat(expiry)
        expiry_str = expiry_dt.strftime("%d %b %Y")
    else:
        expiry_str = "N/A"

    profile_text = (
        f"👤 *MY PROFILE*\n\n"
        f"🆔 User ID: `{user_id}`\n"
        f"👤 Name: {db_user.get('first_name') or 'N/A'}\n"
        f"📛 Username: @{db_user.get('username') or 'N/A'}\n"
        f"✅ Age Verified: {'Yes' if db_user.get('age_verified') else 'No'}\n"
        f"📋 Plan: *{plan}*\n"
        f"⏳ Expiry: {expiry_str}\n"
        f"💳 Payment Status: *{db_user.get('payment_status') or 'pending'}*\n"
        f"🔗 Referrals: {ref_stats['total']}\n"
        f"📅 Joined: {db_user.get('join_date')[:10]}\n\n"
        f"🔑 Referral Code: `{db_user.get('referral_code')}`"
    )

    await query.edit_message_text(
        profile_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Wapas jao", callback_data="back_to_start")]
        ])
    )


async def start_callback(query: CallbackQuery) -> None:
    """Go back to start screen"""
    user_id = query.from_user.id
    stats = get_stats()
    db_user = get_user(user_id)

    welcome_text = get_setting("welcome_text") or "Welcome to VIRAL 99!"

    welcome_msg = (
        f"👋 {welcome_text}\n\n"
        f"🎬 *4,50,000+ Premium HD Videos* – Sab Ek Hi Jagah ✅\n"
        f"• Lifetime Collection ✅\n"
        f"• Daily Updates ✅\n"
        f"• HD Quality ✅\n"
        f"• No Blur, No Low Quality ✅\n"
        f"• Na Ads ✅\n"
        f"• Na Redirect Links ✅\n"
        f"• Payment ke sirf 15 Minutes ke andar Access ✅\n"
        f"• 100% Private & secure ✅\n\n"
        f"👥 {stats['total_users']:,} users already joined\n"
        f"📊 {stats['active_users']:,} active this month · {stats['active_today']} active today\n\n"
        f"👇 *BUY PREMIUM ACCESS* par tap karo aur turant access lo ❤️"
    )

    keyboard = [
        [InlineKeyboardButton("🔥 BUY PREMIUM ACCESS", callback_data="buy_premium")],
        [InlineKeyboardButton("🎬 FREE DEMO", callback_data="free_demo"),
         InlineKeyboardButton("📸 PROOFS", callback_data="proofs")],
        [InlineKeyboardButton("👤 MY PROFILE", callback_data="my_profile"),
         InlineKeyboardButton("🆘 SUPPORT", callback_data="support")],
        [InlineKeyboardButton("📌 MORE OPTIONS", callback_data="more_options")],
    ]

    await query.edit_message_text(
        welcome_msg,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel current operation"""
    await update.message.reply_text(
        "❌ Cancelled.",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END


# ==================== ADMIN COMMANDS ====================

async def admin_auth(update: Update) -> bool:
    """Check if user is admin"""
    return update.effective_user.id in ADMIN_IDS


async def admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin dashboard - full panel"""
    if not await admin_auth(update):
        await update.message.reply_text("⛔ Unauthorized.")
        return

    stats = get_stats()

    # Check if admin panel is locked
    is_locked = get_setting("is_admin_locked") == "1"
    if is_locked:
        password = get_setting("admin_password")
        if password:
            # Ask for password (simple implementation)
            await update.message.reply_text(
                "🔒 *Admin Panel is Locked*\n\n"
                "Please enter the admin password to access.",
                parse_mode=ParseMode.MARKDOWN
            )
            return

    dashboard = (
        f"👑 *Admin Dashboard*\n\n"
        f"📊 *Statistics*\n"
        f"👥 Total Users: *{stats['total_users']:,}*\n"
        f"📅 Active (30d): *{stats['active_users']:,}*\n"
        f"📆 Active Today: *{stats['active_today']}*\n"
        f"✅ Verified: *{stats['age_verified']:,}*\n"
        f"💎 Paid Users: *{stats['paid_users']:,}*\n"
        f"💰 Revenue: *₹{stats['total_revenue']:,}*\n"
        f"⏳ Pending Payments: *{stats['pending_payments']}*\n"
        f"🔗 Referrals: *{stats['total_referrals']}*\n"
        f"⚠️ Suspicious: *{stats['suspicious_users']}*\n\n"
        f"📌 *Admin Actions:*"
    )

    keyboard = [
        [InlineKeyboardButton("📊 Statistics", callback_data="admin_stats")],
        [InlineKeyboardButton("✏️ Welcome Text", callback_data="admin_welcome")],
        [InlineKeyboardButton("🔗 Demo Link", callback_data="admin_demo_link")],
        [InlineKeyboardButton("📦 Manage Plans", callback_data="admin_plans")],
        [InlineKeyboardButton("📋 Pending Payments", callback_data="admin_payments")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")],
        [InlineKeyboardButton("⭐ VIP Users", callback_data="admin_vip")],
        [InlineKeyboardButton("🎫 Coupons", callback_data="admin_coupons")],
        [InlineKeyboardButton("🚨 Suspicious Users", callback_data="admin_suspicious")],
        [InlineKeyboardButton("💳 Manual Pay", callback_data="admin_manual_pay")],
        [InlineKeyboardButton("🔄 Transfer Ownership", callback_data="admin_transfer")],
        [InlineKeyboardButton("👥 User List", callback_data="admin_users")],
        [InlineKeyboardButton("💾 DB Backup", callback_data="admin_backup")],
        [InlineKeyboardButton("🤖 Demo Bot Token", callback_data="admin_token")],
        [InlineKeyboardButton("📺 Backup Channel", callback_data="admin_backup_channel")],
        [InlineKeyboardButton("🎥 Tutorial Video", callback_data="admin_tutorial")],
        [InlineKeyboardButton("🔄 Refresh Cache", callback_data="admin_refresh_cache")],
        [InlineKeyboardButton("💰 Reset Revenue/Stats", callback_data="admin_reset_stats")],
        [InlineKeyboardButton("🔒 Lock Admin Panel", callback_data="admin_lock")],
        [InlineKeyboardButton("📋 CLONE THIS BOT", callback_data="admin_clone")],
        [InlineKeyboardButton("🔙 Back to Bot", callback_data="back_to_start")],
    ]

    await update.message.reply_text(
        dashboard,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin dashboard callbacks"""
    query = update.callback_query
    await query.answer()

    if not await admin_auth(update):
        await query.edit_message_text("⛔ Unauthorized.")
        return

    data = query.data

    if data == "admin_stats":
        await show_admin_stats(query)

    elif data == "admin_welcome":
        await show_admin_welcome(query)

    elif data == "admin_demo_link":
        await show_admin_demo_link(query)

    elif data == "admin_plans":
        await show_admin_plans(query)

    elif data == "admin_payments":
        await show_admin_payments(query)

    elif data == "admin_broadcast":
        await show_admin_broadcast(query)

    elif data == "admin_vip":
        await show_admin_vip(query)

    elif data == "admin_coupons":
        await show_admin_coupons(query)

    elif data == "admin_suspicious":
        await show_admin_suspicious(query)

    elif data == "admin_manual_pay":
        await show_admin_manual_pay(query)

    elif data == "admin_transfer":
        await show_admin_transfer(query)

    elif data == "admin_users":
        await show_admin_users(query)

    elif data == "admin_backup":
        await admin_db_backup(query)

    elif data == "admin_token":
        await show_admin_token(query)

    elif data == "admin_backup_channel":
        await show_admin_backup_channel(query)

    elif data == "admin_tutorial":
        await show_admin_tutorial(query)

    elif data == "admin_refresh_cache":
        await admin_refresh_cache(query)

    elif data == "admin_reset_stats":
        await admin_reset_stats(query)

    elif data == "admin_lock":
        await show_admin_lock(query)

    elif data == "admin_clone":
        await show_admin_clone(query)

    elif data == "admin_back":
        # Go back to admin dashboard
        stats = get_stats()
        dashboard = (
            f"👑 *Admin Dashboard*\n\n"
            f"📊 *Statistics*\n"
            f"👥 Total Users: *{stats['total_users']:,}*\n"
            f"📅 Active (30d): *{stats['active_users']:,}*\n"
            f"📆 Active Today: *{stats['active_today']}*\n"
            f"✅ Verified: *{stats['age_verified']:,}*\n"
            f"💎 Paid Users: *{stats['paid_users']:,}*\n"
            f"💰 Revenue: *₹{stats['total_revenue']:,}*\n"
            f"⏳ Pending Payments: *{stats['pending_payments']}*\n"
            f"🔗 Referrals: *{stats['total_referrals']}*\n"
            f"⚠️ Suspicious: *{stats['suspicious_users']}*\n\n"
            f"📌 *Admin Actions:*"
        )
        keyboard = [
            [InlineKeyboardButton("📊 Statistics", callback_data="admin_stats")],
            [InlineKeyboardButton("✏️ Welcome Text", callback_data="admin_welcome")],
            [InlineKeyboardButton("🔗 Demo Link", callback_data="admin_demo_link")],
            [InlineKeyboardButton("📦 Manage Plans", callback_data="admin_plans")],
            [InlineKeyboardButton("📋 Pending Payments", callback_data="admin_payments")],
            [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")],
            [InlineKeyboardButton("⭐ VIP Users", callback_data="admin_vip")],
            [InlineKeyboardButton("🎫 Coupons", callback_data="admin_coupons")],
            [InlineKeyboardButton("🚨 Suspicious Users", callback_data="admin_suspicious")],
            [InlineKeyboardButton("💳 Manual Pay", callback_data="admin_manual_pay")],
            [InlineKeyboardButton("🔄 Transfer Ownership", callback_data="admin_transfer")],
            [InlineKeyboardButton("👥 User List", callback_data="admin_users")],
            [InlineKeyboardButton("💾 DB Backup", callback_data="admin_backup")],
            [InlineKeyboardButton("🤖 Demo Bot Token", callback_data="admin_token")],
            [InlineKeyboardButton("📺 Backup Channel", callback_data="admin_backup_channel")],
            [InlineKeyboardButton("🎥 Tutorial Video", callback_data="admin_tutorial")],
            [InlineKeyboardButton("🔄 Refresh Cache", callback_data="admin_refresh_cache")],
            [InlineKeyboardButton("💰 Reset Revenue/Stats", callback_data="admin_reset_stats")],
            [InlineKeyboardButton("🔒 Lock Admin Panel", callback_data="admin_lock")],
            [InlineKeyboardButton("📋 CLONE THIS BOT", callback_data="admin_clone")],
            [InlineKeyboardButton("🔙 Back to Bot", callback_data="back_to_start")],
        ]
        await query.edit_message_text(
            dashboard,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif data.startswith("edit_plan_"):
        # Edit plan: format edit_plan_KEY
        key = data.split("_")[-1]
        await show_edit_plan(query, key)

    elif data.startswith("update_plan_"):
        # Update plan: format update_plan_KEY_price_duration_label
        parts = data.split("_")
        key = parts[2]
        price = int(parts[3])
        duration = parts[4] if len(parts) > 4 else "1 Month"
        label = parts[5] if len(parts) > 5 else key
        update_plan(key, price=price, duration=duration, label=label)
        await query.edit_message_text(
            f"✅ Plan *{key}* updated successfully!",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Plans", callback_data="admin_plans")],
                [InlineKeyboardButton("🏠 Admin Panel", callback_data="admin_back")]
            ])
        )
        log_admin_action(query.from_user.id, "edit_plan", f"Updated {key} to price={price}, duration={duration}")

    elif data.startswith("toggle_plan_"):
        key = data.split("_")[-1]
        # Toggle active status
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT is_active FROM plans WHERE key = ?", (key,))
            row = cursor.fetchone()
            if row:
                new_status = 0 if row[0] else 1
                cursor.execute("UPDATE plans SET is_active = ? WHERE key = ?", (new_status, key))
                await query.edit_message_text(
                    f"✅ Plan *{key}* {'activated' if new_status else 'deactivated'}!",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 Back to Plans", callback_data="admin_plans")],
                        [InlineKeyboardButton("🏠 Admin Panel", callback_data="admin_back")]
                    ])
                )
                log_admin_action(query.from_user.id, "toggle_plan", f"{key} set to {'active' if new_status else 'inactive'}")

    elif data.startswith("verify_payment_"):
        payment_id = int(data.split("_")[-1])
        await verify_payment_action(query, payment_id)

    elif data.startswith("reject_payment_"):
        payment_id = int(data.split("_")[-1])
        await reject_payment_action(query, payment_id)

    elif data.startswith("unsuspend_"):
        user_id = int(data.split("_")[-1])
        mark_user_unsuspicious(user_id)
        await query.edit_message_text(
            f"✅ User {user_id} unsuspended.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Suspicious", callback_data="admin_suspicious")],
                [InlineKeyboardButton("🏠 Admin Panel", callback_data="admin_back")]
            ])
        )
        log_admin_action(query.from_user.id, "unsuspend_user", f"User {user_id} unsuspended")

    elif data.startswith("delete_coupon_"):
        coupon_id = int(data.split("_")[-1])
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM coupons WHERE id = ?", (coupon_id,))
        await query.edit_message_text(
            "✅ Coupon deleted.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Coupons", callback_data="admin_coupons")],
                [InlineKeyboardButton("🏠 Admin Panel", callback_data="admin_back")]
            ])
        )
        log_admin_action(query.from_user.id, "delete_coupon", f"Coupon ID {coupon_id} deleted")

    elif data == "admin_panel":
        # Redirect to admin dashboard
        await admin_start(update, context)


# ===== Admin Sub-functions =====

async def show_admin_stats(query: CallbackQuery) -> None:
    stats = get_stats()
    text = (
        f"📊 *Bot Statistics*\n\n"
        f"👥 Total Users: *{stats['total_users']:,}*\n"
        f"📅 Active (30d): *{stats['active_users']:,}*\n"
        f"📆 Active Today: *{stats['active_today']}*\n"
        f"✅ Age Verified: *{stats['age_verified']:,}*\n"
        f"💎 Paid Users: *{stats['paid_users']:,}*\n"
        f"💰 Total Revenue: *₹{stats['total_revenue']:,}*\n"
        f"⏳ Pending Payments: *{stats['pending_payments']}*\n"
        f"🔗 Total Referrals: *{stats['total_referrals']}*\n"
        f"⚠️ Suspicious Users: *{stats['suspicious_users']}*\n"
    )
    await query.edit_message_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Refresh", callback_data="admin_stats")],
            [InlineKeyboardButton("🔙 Back", callback_data="admin_back")]
        ])
    )


async def show_admin_welcome(query: CallbackQuery) -> None:
    current = get_setting("welcome_text") or "Not set"
    await query.edit_message_text(
        f"✏️ *Welcome Text*\n\n"
        f"Current: {current}\n\n"
        f"Send a new welcome text using:\n"
        f"`/set_welcome Your new welcome message`\n\n"
        f"Example:\n"
        f"`/set_welcome Welcome to VIRAL 99! Enjoy unlimited content.`",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="admin_back")]
        ])
    )


async def show_admin_demo_link(query: CallbackQuery) -> None:
    current = get_setting("demo_link") or "Not set"
    await query.edit_message_text(
        f"🔗 *Demo Link*\n\n"
        f"Current: {current}\n\n"
        f"Send a new demo link using:\n"
        f"`/set_demo https://t.me/your_demo_channel`",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="admin_back")]
        ])
    )


async def show_admin_plans(query: CallbackQuery) -> None:
    plans = get_all_plans()
    text = "📦 *Manage Plans*\n\n"
    for p in plans:
        status = "🟢 Active" if p["is_active"] else "🔴 Inactive"
        text += f"• *{p['key']}*: ₹{p['price']} — {p['duration']} ({status})\n"
        text += f"  Edit: /edit_plan {p['key']} price duration label\n"
        text += f"  Toggle: /toggle_plan {p['key']}\n\n"

    text += "\nTo edit a plan, use:\n`/edit_plan PLAN_KEY NEW_PRICE NEW_DURATION NEW_LABEL`\n"
    text += "Example: `/edit_plan VIP 199 \"2 Months\" \"Premium VIP\"`\n\n"
    text += "To toggle active/inactive: `/toggle_plan PLAN_KEY`"

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Refresh", callback_data="admin_plans")],
            [InlineKeyboardButton("🔙 Back", callback_data="admin_back")]
        ])
    )


async def show_edit_plan(query: CallbackQuery, key: str) -> None:
    # We'll use a conversation or just instruct to use commands
    await query.edit_message_text(
        f"✏️ *Edit Plan: {key}*\n\n"
        f"Use the following command to update:\n"
        f"`/edit_plan {key} NEW_PRICE NEW_DURATION NEW_LABEL`\n\n"
        f"Example:\n"
        f"`/edit_plan {key} 199 \"2 Months\" \"Premium\"`\n\n"
        f"To toggle active/inactive:\n"
        f"`/toggle_plan {key}`",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back to Plans", callback_data="admin_plans")]
        ])
    )


async def show_admin_payments(query: CallbackQuery) -> None:
    pending = get_pending_payments()

    if not pending:
        await query.edit_message_text(
            "✅ *No pending payments.*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Refresh", callback_data="admin_payments")],
                [InlineKeyboardButton("🔙 Back", callback_data="admin_back")]
            ])
        )
        return

    text = f"📋 *Pending Payments* ({len(pending)})\n\n"

    for p in pending[:10]:
        text += (
            f"🆔 #{p['id']}\n"
            f"👤 {p['first_name']} (@{p['username'] or 'N/A'})\n"
            f"📋 {p['plan']} — ₹{p['amount']}\n"
            f"📅 {p['created_at'][:10]}\n"
            f"📝 {p['payment_proof'][:50] if p['payment_proof'] else 'No proof'}\n"
            f"---\n"
        )

    if len(pending) > 10:
        text += f"\n... and {len(pending) - 10} more."

    keyboard = []
    for p in pending[:5]:
        keyboard.append([
            InlineKeyboardButton(
                f"✅ #{p['id']} - {p['first_name']}",
                callback_data=f"verify_payment_{p['id']}"
            ),
            InlineKeyboardButton(
                f"❌ Reject",
                callback_data=f"reject_payment_{p['id']}"
            )
        ])

    keyboard.append([InlineKeyboardButton("🔄 Refresh", callback_data="admin_payments")])
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="admin_back")])

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def verify_payment_action(query: CallbackQuery, payment_id: int) -> None:
    admin_id = query.from_user.id

    if verify_payment(payment_id, admin_id):
        log_admin_action(admin_id, "verify_payment", f"Payment #{payment_id} verified")

        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT p.*, u.first_name, u.username
                FROM payments p
                JOIN users u ON p.user_id = u.user_id
                WHERE p.id = ?
            """, (payment_id,))
            payment = cursor.fetchone()

        if payment:
            try:
                await context.bot.send_message(
                    payment["user_id"],
                    f"🎉 *Payment Verified!*\n\n"
                    f"✅ Aapka payment verify ho gaya hai!\n"
                    f"📋 Plan: *{payment['plan']}*\n"
                    f"💰 Amount: ₹{payment['amount']}\n\n"
                    f"🔓 Ab aap premium content access kar sakte hain!\n"
                    f"❤️ Thank you for choosing VIRAL 99!",
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception as e:
                logger.error(f"Failed to notify user {payment['user_id']}: {e}")

        await query.edit_message_text(
            f"✅ *Payment #{payment_id} verified successfully!*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Refresh", callback_data="admin_payments")],
                [InlineKeyboardButton("🔙 Back", callback_data="admin_back")]
            ])
        )
    else:
        await query.edit_message_text(
            f"❌ *Error verifying payment #{payment_id}*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Refresh", callback_data="admin_payments")]
            ])
        )


async def reject_payment_action(query: CallbackQuery, payment_id: int) -> None:
    admin_id = query.from_user.id

    if reject_payment(payment_id, admin_id):
        log_admin_action(admin_id, "reject_payment", f"Payment #{payment_id} rejected")

        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT p.*, u.first_name
                FROM payments p
                JOIN users u ON p.user_id = u.user_id
                WHERE p.id = ?
            """, (payment_id,))
            payment = cursor.fetchone()

        if payment:
            try:
                await context.bot.send_message(
                    payment["user_id"],
                    f"❌ *Payment Rejected*\n\n"
                    f"Aapka payment reject kar diya gaya hai.\n"
                    f"📋 Plan: *{payment['plan']}*\n"
                    f"💰 Amount: ₹{payment['amount']}\n\n"
                    f"⚠️ Reason: Payment proof invalid or not found.\n"
                    f"Please contact support for assistance.",
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception as e:
                logger.error(f"Failed to notify user {payment['user_id']}: {e}")

        await query.edit_message_text(
            f"❌ *Payment #{payment_id} rejected!*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Refresh", callback_data="admin_payments")],
                [InlineKeyboardButton("🔙 Back", callback_data="admin_back")]
            ])
        )
    else:
        await query.edit_message_text(
            f"❌ *Error rejecting payment #{payment_id}*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Refresh", callback_data="admin_payments")]
            ])
        )


async def show_admin_broadcast(query: CallbackQuery) -> None:
    await query.edit_message_text(
        "📢 *Broadcast*\n\n"
        "Send a message to all users.\n"
        "Use: `/broadcast Your message here`\n\n"
        "Example:\n"
        "`/broadcast New content added! Check it out.`\n\n"
        "⚠️ Message will be sent to ALL users.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="admin_back")]
        ])
    )


async def show_admin_vip(query: CallbackQuery) -> None:
    vips = get_vip_users()
    if not vips:
        await query.edit_message_text(
            "⭐ *VIP Users*\n\nNo active VIP users.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="admin_back")]
            ])
        )
        return

    text = f"⭐ *VIP Users* ({len(vips)})\n\n"
    for u in vips[:20]:
        text += f"🆔 `{u['user_id']}` — {u.get('first_name', 'N/A')} (@{u.get('username', 'N/A')})\n"
        text += f"   📋 {u['plan']} | Expires: {u['plan_expiry'][:10] if u['plan_expiry'] else 'N/A'}\n"

    if len(vips) > 20:
        text += f"\n... and {len(vips) - 20} more."

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Refresh", callback_data="admin_vip")],
            [InlineKeyboardButton("🔙 Back", callback_data="admin_back")]
        ])
    )


async def show_admin_coupons(query: CallbackQuery) -> None:
    coupons = get_all_coupons()
    text = "🎫 *Coupons*\n\n"
    if coupons:
        for c in coupons[:10]:
            status = "🟢 Active" if c["is_active"] and c["expiry"] > datetime.now().isoformat() and c["used_count"] < c["max_uses"] else "🔴 Expired/Used"
            text += f"• `{c['code']}` — {c['discount_percent']}% off, used {c['used_count']}/{c['max_uses']}, {status}\n"
            text += f"  Delete: /delete_coupon {c['id']}\n"
    else:
        text += "No coupons available.\n"

    text += "\nTo generate a new coupon:\n"
    text += "`/generate_coupon DISCOUNT_PERCENT MAX_USES EXPIRY_DAYS`\n"
    text += "Example: `/generate_coupon 20 5 30`"

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Refresh", callback_data="admin_coupons")],
            [InlineKeyboardButton("🔙 Back", callback_data="admin_back")]
        ])
    )


async def show_admin_suspicious(query: CallbackQuery) -> None:
    sus = get_suspicious_users()
    if not sus:
        await query.edit_message_text(
            "🚨 *Suspicious Users*\n\nNo suspicious users.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="admin_back")]
            ])
        )
        return

    text = "🚨 *Suspicious Users*\n\n"
    for u in sus[:20]:
        text += f"🆔 `{u['user_id']}` — {u.get('first_name', 'N/A')} (@{u.get('username', 'N/A')})\n"
        text += f"   Reason: {u.get('suspension_reason', 'No reason')}\n"
        text += f"   Unsuspend: /unsuspend {u['user_id']}\n"

    if len(sus) > 20:
        text += f"\n... and {len(sus) - 20} more."

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Refresh", callback_data="admin_suspicious")],
            [InlineKeyboardButton("🔙 Back", callback_data="admin_back")]
        ])
    )


async def show_admin_manual_pay(query: CallbackQuery) -> None:
    await query.edit_message_text(
        "💳 *Manual Pay*\n\n"
        "Manually mark a user as paid.\n"
        "Use: `/manual_pay USER_ID PLAN_KEY`\n\n"
        "Example:\n"
        "`/manual_pay 123456789 VIP`\n\n"
        "Available plans: STANDARD, VIP, CZF, KAMASUTRA",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="admin_back")]
        ])
    )


async def show_admin_transfer(query: CallbackQuery) -> None:
    await query.edit_message_text(
        "🔄 *Transfer Ownership*\n\n"
        "This feature allows you to transfer bot ownership to another admin.\n\n"
        "To transfer, use:\n"
        "`/transfer_owner NEW_OWNER_ID`\n\n"
        "⚠️ This will add the new owner as admin and remove you (if you want).\n"
        "Implement carefully.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="admin_back")]
        ])
    )


async def show_admin_users(query: CallbackQuery) -> None:
    users = get_all_users(include_suspicious=True)
    text = f"👥 *All Users* ({len(users)})\n\n"

    for u in users[:10]:
        text += f"🆔 `{u['user_id']}` — {u.get('first_name', 'N/A')}\n"
        text += f"   📋 {u.get('plan') or 'None'} | 💳 {u.get('payment_status') or 'pending'}\n"
        text += f"   📅 {u.get('join_date', '')[:10]}\n"

    if len(users) > 10:
        text += f"\n... and {len(users) - 10} more."

    text += f"\n\n📊 *Summary:*\n"
    stats = get_stats()
    text += f"Paid: {stats['paid_users']} | Pending: {stats['pending_payments']}"

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 Export Users", callback_data="admin_export_users")],
            [InlineKeyboardButton("🔄 Refresh", callback_data="admin_users")],
            [InlineKeyboardButton("🔙 Back", callback_data="admin_back")]
        ])
    )


async def admin_db_backup(query: CallbackQuery) -> None:
    # Send the database file
    try:
        with open(DATABASE_FILE, 'rb') as f:
            await context.bot.send_document(
                chat_id=query.from_user.id,
                document=f,
                filename=f"viral99_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db",
                caption="💾 Database backup"
            )
        log_admin_action(query.from_user.id, "db_backup", "Database backup downloaded")
        await query.edit_message_text(
            "✅ Database backup sent!",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="admin_back")]
            ])
        )
    except Exception as e:
        await query.edit_message_text(
            f"❌ Error creating backup: {e}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="admin_back")]
            ])
        )


async def show_admin_token(query: CallbackQuery) -> None:
    # Show bot token (masked)
    token = BOT_TOKEN
    masked = token[:5] + "*" * (len(token) - 10) + token[-5:]
    await query.edit_message_text(
        f"🤖 *Bot Token*\n\n"
        f"Current token: `{masked}`\n\n"
        f"⚠️ Keep this secret!",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="admin_back")]
        ])
    )


async def show_admin_backup_channel(query: CallbackQuery) -> None:
    current = get_setting("backup_channel") or "Not set"
    await query.edit_message_text(
        f"📺 *Backup Channel*\n\n"
        f"Current: {current}\n\n"
        f"Set a backup channel using:\n"
        f"`/set_backup_channel @channel_username`",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="admin_back")]
        ])
    )


async def show_admin_tutorial(query: CallbackQuery) -> None:
    current = get_setting("tutorial_video") or "Not set"
    await query.edit_message_text(
        f"🎥 *Tutorial Video*\n\n"
        f"Current: {current}\n\n"
        f"Set a tutorial video link using:\n"
        f"`/set_tutorial https://youtu.be/...`",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="admin_back")]
        ])
    )


async def admin_refresh_cache(query: CallbackQuery) -> None:
    # Clear any caches (none in this implementation)
    await query.edit_message_text(
        "🔄 *Cache Refreshed*\n\n"
        "All caches have been cleared.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="admin_back")]
        ])
    )
    log_admin_action(query.from_user.id, "refresh_cache", "Cache refreshed")


async def admin_reset_stats(query: CallbackQuery) -> None:
    # Reset revenue stats (dangerous)
    # We'll just reset the total revenue in settings? But it's computed from payments.
    # We'll add a confirmation.
    await query.edit_message_text(
        "💰 *Reset Revenue/Stats*\n\n"
        "⚠️ This will reset the total revenue counter to 0.\n"
        "This action cannot be undone!\n\n"
        "Are you sure?",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Yes, Reset", callback_data="admin_reset_confirm")],
            [InlineKeyboardButton("❌ Cancel", callback_data="admin_back")]
        ])
    )


async def admin_reset_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not await admin_auth(update):
        await query.edit_message_text("⛔ Unauthorized.")
        return

    # Reset revenue by setting all payments amount to 0? Or just reset the sum?
    # We'll just reset the sum by deleting the payments? That's too destructive.
    # We'll just set a flag or clear the payments? Better to keep history.
    # Let's just reset the total revenue stored in settings? But we compute from payments.
    # We'll update all payments to amount 0? Not good.
    # Safer: just reset the stats by deleting the payments? No.
    # We'll just inform that it's not implemented fully.
    await query.edit_message_text(
        "⚠️ *Reset Revenue/Stats*\n\n"
        "This feature is not fully implemented to prevent data loss.\n"
        "You can manually reset by clearing the payments table via SQLite.\n\n"
        "Contact developer for assistance.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="admin_back")]
        ])
    )


async def show_admin_lock(query: CallbackQuery) -> None:
    current = get_setting("is_admin_locked") == "1"
    status = "🔒 Locked" if current else "🔓 Unlocked"
    await query.edit_message_text(
        f"🔒 *Admin Panel Lock*\n\n"
        f"Current: {status}\n\n"
        f"To lock the panel, set a password:\n"
        f"`/set_admin_password YOUR_PASSWORD`\n\n"
        f"To unlock:\n"
        f"`/remove_admin_password`",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="admin_back")]
        ])
    )


async def show_admin_clone(query: CallbackQuery) -> None:
    await query.edit_message_text(
        "📋 *CLONE THIS BOT*\n\n"
        "To clone this bot, follow these steps:\n\n"
        "1. Copy the source code from the developer.\n"
        "2. Replace BOT_TOKEN and ADMIN_IDS.\n"
        "3. Deploy on your server.\n"
        "4. Run the bot.\n\n"
        "For more info, contact @developer.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="admin_back")]
        ])
    )


# ===== Admin Command Handlers (text commands) =====

async def set_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await admin_auth(update):
        await update.message.reply_text("⛔ Unauthorized.")
        return
    text = " ".join(context.args)
    if not text:
        await update.message.reply_text("❌ Please provide a welcome text.")
        return
    set_setting("welcome_text", text)
    log_admin_action(update.effective_user.id, "set_welcome", text)
    await update.message.reply_text(f"✅ Welcome text updated to:\n\n{text}")


async def set_demo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await admin_auth(update):
        await update.message.reply_text("⛔ Unauthorized.")
        return
    link = " ".join(context.args)
    if not link:
        await update.message.reply_text("❌ Please provide a demo link.")
        return
    set_setting("demo_link", link)
    log_admin_action(update.effective_user.id, "set_demo", link)
    await update.message.reply_text(f"✅ Demo link updated to: {link}")


async def set_backup_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await admin_auth(update):
        await update.message.reply_text("⛔ Unauthorized.")
        return
    channel = " ".join(context.args)
    if not channel:
        await update.message.reply_text("❌ Please provide a channel username.")
        return
    set_setting("backup_channel", channel)
    log_admin_action(update.effective_user.id, "set_backup_channel", channel)
    await update.message.reply_text(f"✅ Backup channel set to: {channel}")


async def set_tutorial(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await admin_auth(update):
        await update.message.reply_text("⛔ Unauthorized.")
        return
    link = " ".join(context.args)
    if not link:
        await update.message.reply_text("❌ Please provide a tutorial link.")
        return
    set_setting("tutorial_video", link)
    log_admin_action(update.effective_user.id, "set_tutorial", link)
    await update.message.reply_text(f"✅ Tutorial video link set to: {link}")


async def edit_plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await admin_auth(update):
        await update.message.reply_text("⛔ Unauthorized.")
        return
    args = context.args
    if len(args) < 4:
        await update.message.reply_text(
            "❌ Usage: /edit_plan KEY NEW_PRICE NEW_DURATION NEW_LABEL\n"
            "Example: /edit_plan VIP 199 \"2 Months\" \"Premium VIP\""
        )
        return
    key = args[0]
    try:
        price = int(args[1])
    except ValueError:
        await update.message.reply_text("❌ Price must be a number.")
        return
    duration = args[2] if len(args) > 2 else "1 Month"
    label = " ".join(args[3:]) if len(args) > 3 else key

    update_plan(key, price=price, duration=duration, label=label)
    log_admin_action(update.effective_user.id, "edit_plan", f"{key} -> price={price}, duration={duration}, label={label}")
    await update.message.reply_text(f"✅ Plan *{key}* updated successfully!", parse_mode=ParseMode.MARKDOWN)


async def toggle_plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await admin_auth(update):
        await update.message.reply_text("⛔ Unauthorized.")
        return
    if not context.args:
        await update.message.reply_text("❌ Usage: /toggle_plan PLAN_KEY")
        return
    key = context.args[0]
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT is_active FROM plans WHERE key = ?", (key,))
        row = cursor.fetchone()
        if not row:
            await update.message.reply_text(f"❌ Plan {key} not found.")
            return
        new_status = 0 if row[0] else 1
        cursor.execute("UPDATE plans SET is_active = ? WHERE key = ?", (new_status, key))
    log_admin_action(update.effective_user.id, "toggle_plan", f"{key} set to {'active' if new_status else 'inactive'}")
    await update.message.reply_text(f"✅ Plan *{key}* {'activated' if new_status else 'deactivated'}!", parse_mode=ParseMode.MARKDOWN)


async def generate_coupon_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await admin_auth(update):
        await update.message.reply_text("⛔ Unauthorized.")
        return
    args = context.args
    if len(args) < 3:
        await update.message.reply_text(
            "❌ Usage: /generate_coupon DISCOUNT MAX_USES EXPIRY_DAYS\n"
            "Example: /generate_coupon 20 5 30"
        )
        return
    try:
        discount = int(args[0])
        max_uses = int(args[1])
        expiry_days = int(args[2])
    except ValueError:
        await update.message.reply_text("❌ Please provide valid numbers.")
        return
    code = generate_coupon(discount, max_uses, expiry_days)
    log_admin_action(update.effective_user.id, "generate_coupon", f"{code} ({discount}% off, {max_uses} uses, {expiry_days} days)")
    await update.message.reply_text(
        f"✅ Coupon generated!\n\n"
        f"Code: `{code}`\n"
        f"Discount: {discount}%\n"
        f"Max uses: {max_uses}\n"
        f"Expires in: {expiry_days} days",
        parse_mode=ParseMode.MARKDOWN
    )


async def delete_coupon_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await admin_auth(update):
        await update.message.reply_text("⛔ Unauthorized.")
        return
    if not context.args:
        await update.message.reply_text("❌ Usage: /delete_coupon COUPON_ID")
        return
    try:
        coupon_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid ID.")
        return
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM coupons WHERE id = ?", (coupon_id,))
    log_admin_action(update.effective_user.id, "delete_coupon", f"Coupon ID {coupon_id} deleted")
    await update.message.reply_text(f"✅ Coupon {coupon_id} deleted.")


async def manual_pay_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await admin_auth(update):
        await update.message.reply_text("⛔ Unauthorized.")
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "❌ Usage: /manual_pay USER_ID PLAN_KEY\n"
            "Example: /manual_pay 123456789 VIP"
        )
        return
    try:
        user_id = int(args[0])
        plan = args[1].upper()
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID.")
        return

    # Check if plan exists
    plans = get_all_plans()
    plan_keys = [p["key"] for p in plans]
    if plan not in plan_keys:
        await update.message.reply_text(f"❌ Invalid plan. Available: {', '.join(plan_keys)}")
        return

    if manual_pay_user(user_id, plan, update.effective_user.id):
        await update.message.reply_text(f"✅ User {user_id} marked as paid for plan {plan}.")
        # Notify user
        try:
            await context.bot.send_message(
                user_id,
                f"🎉 *Manual Payment Applied!*\n\n"
                f"Admin ne aapko manually {plan} plan activate kar diya hai.\n"
                f"Ab aap premium content access kar sakte hain!",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Failed to notify user {user_id}: {e}")
    else:
        await update.message.reply_text(f"❌ User {user_id} not found.")


async def unsuspend_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await admin_auth(update):
        await update.message.reply_text("⛔ Unauthorized.")
        return
    if not context.args:
        await update.message.reply_text("❌ Usage: /unsuspend USER_ID")
        return
    try:
        user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID.")
        return
    mark_user_unsuspicious(user_id)
    log_admin_action(update.effective_user.id, "unsuspend_user", f"User {user_id} unsuspended")
    await update.message.reply_text(f"✅ User {user_id} unsuspended.")


async def set_admin_password_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await admin_auth(update):
        await update.message.reply_text("⛔ Unauthorized.")
        return
    if not context.args:
        await update.message.reply_text("❌ Usage: /set_admin_password NEW_PASSWORD")
        return
    password = " ".join(context.args)
    set_setting("admin_password", password)
    set_setting("is_admin_locked", "1")
    log_admin_action(update.effective_user.id, "set_admin_password", "Password set")
    await update.message.reply_text("✅ Admin panel locked with password.")


async def remove_admin_password_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await admin_auth(update):
        await update.message.reply_text("⛔ Unauthorized.")
        return
    set_setting("admin_password", "")
    set_setting("is_admin_locked", "0")
    log_admin_action(update.effective_user.id, "remove_admin_password", "Password removed")
    await update.message.reply_text("✅ Admin panel unlocked.")


async def admin_password_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle password entry for locked admin panel"""
    if not await admin_auth(update):
        return
    password = get_setting("admin_password")
    if not password:
        return
    # If user sent a message and it matches password
    if update.message.text == password:
        # Unlock temporarily for this session?
        # We'll just allow access for this command
        await admin_start(update, context)
    else:
        await update.message.reply_text("❌ Incorrect password.")


async def admin_broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await admin_auth(update):
        await update.message.reply_text("⛔ Unauthorized.")
        return

    # Get message from command
    message_text = " ".join(context.args)
    if not message_text:
        await update.message.reply_text(
            "❌ Please provide a message.\n"
            "Usage: /broadcast <message>"
        )
        return

    # Get all users
    users = get_all_users(include_suspicious=False)
    recipients = len(users)

    # Send confirmation
    confirm_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm Broadcast", callback_data=f"broadcast_confirm_{len(message_text)}_{recipients}")],
        [InlineKeyboardButton("❌ Cancel", callback_data="admin_back")]
    ])

    # Store message in context for later use
    context.user_data["broadcast_message"] = message_text

    await update.message.reply_text(
        f"📢 *Broadcast Preview*\n\n"
        f"Message: {message_text[:200]}...\n\n"
        f"👥 Recipients: {recipients} users\n\n"
        f"⚠️ Confirm to send.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=confirm_keyboard
    )


async def broadcast_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Confirm and send broadcast"""
    query = update.callback_query
    await query.answer()

    if not await admin_auth(update):
        await query.edit_message_text("⛔ Unauthorized.")
        return

    # Get the message from context
    message_text = context.user_data.get("broadcast_message")
    if not message_text:
        await query.edit_message_text("❌ No broadcast message found.")
        return

    # Get all users
    users = get_all_users(include_suspicious=False)
    recipients = len(users)

    # Send broadcast
    sent = 0
    for u in users:
        try:
            await context.bot.send_message(
                u["user_id"],
                f"📢 *Broadcast*\n\n{message_text}",
                parse_mode=ParseMode.MARKDOWN
            )
            sent += 1
            await asyncio.sleep(0.05)  # Avoid rate limits
        except Exception as e:
            logger.error(f"Failed to send to {u['user_id']}: {e}")

    # Log
    log_admin_action(update.effective_user.id, "broadcast", f"Sent to {sent}/{recipients} users")

    await query.edit_message_text(
        f"✅ *Broadcast sent!*\n\n"
        f"📤 Sent to {sent} out of {recipients} users.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="admin_back")]
        ])
    )


async def admin_export_users_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await admin_auth(update):
        await update.message.reply_text("⛔ Unauthorized.")
        return

    users = get_all_users(include_suspicious=True)

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["User ID", "Username", "First Name", "Last Name", "Age Verified",
                     "Plan", "Plan Expiry", "Payment Status", "Referral Code", "Join Date", "Suspicious"])

    for u in users:
        writer.writerow([
            u["user_id"],
            u["username"] or "",
            u["first_name"] or "",
            u["last_name"] or "",
            "Yes" if u["age_verified"] else "No",
            u["plan"] or "",
            u["plan_expiry"] or "",
            u["payment_status"] or "",
            u["referral_code"] or "",
            u["join_date"] or "",
            "Yes" if u["is_suspicious"] else "No"
        ])

    csv_data = output.getvalue()
    output.close()

    await update.message.reply_document(
        document=csv_data.encode('utf-8'),
        filename=f"users_export_{datetime.now().strftime('%Y%m%d')}.csv",
        caption=f"📥 Users Export — {len(users)} users"
    )
    log_admin_action(update.effective_user.id, "export_users", f"Exported {len(users)} users")


# ==================== MAIN APPLICATION ====================

def main():
    """Main bot application entry point"""
    # Initialize database
    init_database()

    # Create application
    application = Application.builder().token(BOT_TOKEN).build()

    # ===== Conversation Handlers =====
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CallbackQueryHandler(plan_callback, pattern="^plan_"),
            CallbackQueryHandler(payment_done_callback, pattern="^payment_done$"),
            CallbackQueryHandler(send_proof_callback, pattern="^send_proof$"),
        ],
        states={
            PAYMENT_PROOF: [
                MessageHandler(filters.PHOTO, handle_payment_proof),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_payment_proof),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CallbackQueryHandler(lambda u, c: None, pattern="^back_to_start$"),
        ],
        allow_reentry=True,
    )

    application.add_handler(conv_handler)

    # ===== Command Handlers =====
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_start))
    application.add_handler(CommandHandler("broadcast", admin_broadcast_command))
    application.add_handler(CommandHandler("export", admin_export_users_command))

    # Admin settings commands
    application.add_handler(CommandHandler("set_welcome", set_welcome))
    application.add_handler(CommandHandler("set_demo", set_demo))
    application.add_handler(CommandHandler("set_backup_channel", set_backup_channel))
    application.add_handler(CommandHandler("set_tutorial", set_tutorial))
    application.add_handler(CommandHandler("edit_plan", edit_plan_command))
    application.add_handler(CommandHandler("toggle_plan", toggle_plan_command))
    application.add_handler(CommandHandler("generate_coupon", generate_coupon_command))
    application.add_handler(CommandHandler("delete_coupon", delete_coupon_command))
    application.add_handler(CommandHandler("manual_pay", manual_pay_command))
    application.add_handler(CommandHandler("unsuspend", unsuspend_command))
    application.add_handler(CommandHandler("set_admin_password", set_admin_password_command))
    application.add_handler(CommandHandler("remove_admin_password", remove_admin_password_command))

    # ===== Callback Query Handlers =====
    application.add_handler(CallbackQueryHandler(button_callback, pattern="^(buy_premium|free_demo|proofs|my_profile|support|more_options|faq|refer_earn|share_ref|status|back_to_start|renew_plan)$"))
    application.add_handler(CallbackQueryHandler(age_callback, pattern="^age_(yes|no)$"))
    application.add_handler(CallbackQueryHandler(plan_callback, pattern="^plan_"))
    application.add_handler(CallbackQueryHandler(payment_done_callback, pattern="^payment_done$"))
    application.add_handler(CallbackQueryHandler(send_proof_callback, pattern="^send_proof$"))
    application.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin_"))
    application.add_handler(CallbackQueryHandler(broadcast_confirm_callback, pattern="^broadcast_confirm_"))
    application.add_handler(CallbackQueryHandler(admin_reset_confirm, pattern="^admin_reset_confirm$"))

    # ===== Message Handlers (fallback) =====
    application.add_handler(MessageHandler(filters.PHOTO, handle_payment_proof))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_payment_proof))

    # ===== Error Handler =====
    async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        logger.error(f"Update {update} caused error {context.error}")

    application.add_error_handler(error_handler)

    # ===== Start the bot =====
    logger.info("VIRAL 99 Bot started!")
    print("\n" + "="*50)
    print("🤖 VIRAL 99 BOT RUNNING")
    print("="*50)
    print(f"📊 Admin IDs: {ADMIN_IDS}")
    print(f"💾 Database: {DATABASE_FILE}")
    print(f"📋 Plans: {', '.join([p['key'] for p in get_all_plans()])}")
    print("="*50 + "\n")

    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()