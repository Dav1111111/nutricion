"""
Миграция для добавления полей автопродления в таблицу user_subscriptions
"""
import asyncio
from sqlalchemy import text
from database.connection import db_connection

async def upgrade():
    """Добавляем новые поля для автопродления"""
    async with db_connection.engine.begin() as conn:
        # Добавляем поля для автопродления
        await conn.execute(text("""
            ALTER TABLE user_subscriptions 
            ADD COLUMN is_auto_renewal BOOLEAN DEFAULT TRUE;
        """))
        
        await conn.execute(text("""
            ALTER TABLE user_subscriptions 
            ADD COLUMN parent_payment_id VARCHAR(255);
        """))
        
        await conn.execute(text("""
            ALTER TABLE user_subscriptions 
            ADD COLUMN next_payment_date TIMESTAMP;
        """))
        
        await conn.execute(text("""
            ALTER TABLE user_subscriptions 
            ADD COLUMN renewal_attempts INTEGER DEFAULT 0;
        """))
        
        await conn.execute(text("""
            ALTER TABLE user_subscriptions 
            ADD COLUMN last_renewal_attempt TIMESTAMP;
        """))
        
        print("✅ Миграция выполнена успешно")

async def downgrade():
    """Откат миграции"""
    async with db_connection.engine.begin() as conn:
        await conn.execute(text("""
            ALTER TABLE user_subscriptions 
            DROP COLUMN is_auto_renewal,
            DROP COLUMN parent_payment_id,
            DROP COLUMN next_payment_date,
            DROP COLUMN renewal_attempts,
            DROP COLUMN last_renewal_attempt;
        """))
        print("✅ Откат миграции выполнен")

if __name__ == "__main__":
    asyncio.run(upgrade()) 