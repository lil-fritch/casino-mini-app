import random
from datetime import datetime, timezone
import hashlib
import secrets
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils.timezone import localtime
import uuid

from django.utils import timezone

from app.utils import generate_initial_client_seed

from django.db import models
from decimal import Decimal
from datetime import timedelta

class Site(models.Model):
    users_online = models.IntegerField(default=0)
    last_online_update = models.DateTimeField(default=timezone.now)

    def update_users_online_fake(self):
        now = timezone.now()
        now = localtime(timezone.now())
        if now - self.last_online_update < timedelta(minutes=1):
            return

        hour = now.hour
        
        base_online_by_hour = {
            0: 7,  1: 1,  2: 1,  3: 1,  4: 1,  5: 2,
            6: 4,  7: 6,  8: 8,  9: 10, 10: 12, 11: 14,
            12: 16, 13: 17, 14: 18, 15: 19, 16: 20,
            17: 22, 18: 24, 19: 25, 20: 24, 21: 22,
            22: 16, 23: 12
        }

        base_users = base_online_by_hour.get(hour, 5)

        fluctuation = random.randint(-2, 2)

        new_value = base_users + fluctuation
        new_value = max(0, new_value)

        self.users_online = new_value
        self.last_online_update = now
        self.save()

class Balance(models.Model):
    user = models.OneToOneField('User', on_delete=models.CASCADE, related_name='balance')
    balance_raw = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('00.00'))
    balance_display = models.DecimalField(max_digits=10, decimal_places=0, default=0)

    def add_balance(self, amount: int):
        self.balance_raw += Decimal(amount)
        self.balance_display = int(self.balance_raw)
        self.save()

    def subtract_balance(self, amount: int):
        self.balance_raw -= Decimal(amount)
        self.balance_display = int(self.balance_raw)
        self.save()

    @property
    def balance(self):
        return self.balance_raw

    def __str__(self):
        return f"Balance for {self.user.username}: {self.balance_raw}"

class User(AbstractUser):
    password = models.CharField(max_length=128, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    site_id = models.CharField(max_length=10, unique=True, blank=True, db_index=True)
    telegram_id = models.CharField(max_length=64, unique=True, null=True, blank=True, db_index=True)
    referrer = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.SET_NULL, related_name='referred_users'
    )
    photo_url = models.URLField(null=True, blank=True)
    is_premium = models.BooleanField(default=False)
    timezone = models.CharField(max_length=64, default='UTC')
    timestamp = models.DateTimeField(auto_now_add=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    ban = models.BooleanField(default=False)
    
    def save(self, *args, **kwargs):
        if not self.site_id:
            self.site_id = self.generate_unique_id()

        if self.pk:
            old_instance = User.objects.get(pk=self.pk)
            if not old_instance.ban and self.ban:
                Notification.objects.create(
                    user=self,
                    message_key='ban',
                    type='destructive'
                )

        super().save(*args, **kwargs)
    
    @staticmethod
    def generate_unique_id():
        while True:
            new_id = str(uuid.uuid4())[:8]
            if not User.objects.filter(site_id=new_id).exists():
                return new_id
        
    def get_profile_url(self):
        return f"/profile/{self.site_id}/"
    
    def get_user_name(self):
        return f"{self.first_name} {self.last_name}" if self.first_name or self.last_name else f"{self.custom_id}"
    
    def __str__(self):
        return self.username

class UserSettings(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='settings')
    send_notifications_to_bot = models.BooleanField(default=True)
    client_seed = models.CharField(max_length=64, default=generate_initial_client_seed)
    server_seed = models.CharField(max_length=64, blank=True, null=True)
    withdrawal_invoice = models.URLField(null=True, blank=True)
    language = models.CharField(max_length=8, null=True, blank=True)
    show_profile = models.BooleanField(default=True)
    
    def generate_server_seed(self):
        new_seed = secrets.token_hex(16)
        self.server_seed = new_seed
        self.save()
        return new_seed

    def get_server_seed_hash(self):
        if self.server_seed:
            return hashlib.sha256(self.server_seed.encode()).hexdigest()
        return None
    
    def __str__(self):
        return f"Settings for {self.user.username}"

class Transaction(models.Model):
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    timestamp = models.DateTimeField(auto_now_add=True)

    def amount_in_dollars(self):
        return f'{(self.amount / 100)}$'
    
    def amount_display(self):
        return f'{int(self.amount)}'
    
    class Meta:
        abstract = True

class Deposit(Transaction):
    PAYMENT_SYSTEMS = [
        ('cryptobot', _('CryptoBot')),
    ]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='deposits')
    payment_system = models.CharField(max_length=10, choices=PAYMENT_SYSTEMS)
    class Meta:
        ordering = ['-timestamp']
        
class Withdrawal(Transaction):
    PAYMENT_SYSTEMS = [
        ('cryptobot', _('CryptoBot')),
    ]
    
    STATUS_CHOICES = [
        ('pending', _('Pending confirmation')),
        ('approved', _('Approved')),
        ('canceled', _('Canceled')),
        ('locked', _('Locked')),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='withdrawals')
    payment_system = models.CharField(max_length=50, choices=PAYMENT_SYSTEMS)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    proof_link = models.URLField(null=True, blank=True)
    
    def approve(self):
        self.status = 'approved'
        self.save()

    def cancel(self):
        self.status = 'canceled'
        self.save()

    def lock(self):
        self.status = 'locked'
        self.save()
        
    class Meta:
        ordering = ['-timestamp']

class Notification(models.Model):
    NOTIFICATION_TYPES = (
        ('info', _('Information')),
        ('success', _('Success')),
        ('destructive', _('Destructive')),
    )
    MESSAGE_KEYS = (
        (_('deposit_success'), _('Deposit success')),
        
        (_('withdrawal_approved'), _('Withdrawal approved')),
        (_('withdrawal_rejected'), _('Withdrawal rejected')),
        (_('withdrawal_deleted'), _('Withdrawal deleted')),
        
        (_('withdrawal_info'), _('Withdrawal info')),
        (_('withdrawal_cancel'), _('Withdrawal canceled')),
        
        (_('registration_with_referral_code_success'), _('Registration with referral code success')),  
        (_('invitation_success'), _('Invitation success')),
        
        (_('ban'), _('Ban')),
        (_('admin_notification'), 'Admin notification'),
        (_('new_withdrawal_request'), 'New withdrawal request'),
        (_('new_user_registered'), 'New user registered'),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    message_key = models.CharField(max_length=50, choices=MESSAGE_KEYS)
    message_params = models.JSONField(default=dict)
    url = models.URLField(null=True, blank=True)
    type = models.CharField(max_length=50, choices=NOTIFICATION_TYPES, default='info')
    is_read = models.BooleanField(default=False)
    timestamp = models.DateTimeField(auto_now_add=True)
    
    higher_priority = models.BooleanField(default=False)

    def __str__(self):
        return f"Notification for {self.user.username} - {self.type}"
           
    def get_message(self):
        return _(self.message_key) % self.message_params
    
    def define_add_or_subtract(self):
        if self.message_key in ['withdrawal_info']:
            return 'subtract'
        return 'add'
    
    @classmethod
    def get_messge_by_key_and_params(cls, key, params):
        return _(key) % params
    
    class Meta:
        ordering = ['-timestamp']

class Game(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='games')
    total_bet = models.DecimalField(max_digits=10, decimal_places=2)
    side_2 = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    side_3 = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    side_4 = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    side_5 = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    side_6 = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    client_seed = models.CharField(max_length=64)
    server_seed = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    def get_server_seed_hash(self):
        if self.server_seed:
            return hashlib.sha256(self.server_seed.encode()).hexdigest()
        return None
    
    def get_check_url(self):
        return f"/check/?ss={self.server_seed}&cs={self.client_seed}"
    
    def get_win_chance(self):
        sides = [self.side_2, self.side_3, self.side_4, self.side_5, self.side_6]
        non_zero_count = sum(1 for side in sides if side > 0)
        return f"{int(non_zero_count/6*100)}%"
        
class GameResult(models.Model):
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name='results')
    rolled_number = models.IntegerField()
    is_win = models.BooleanField(default=False)
    win_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)        

    def __str__(self):
        return f"Result: {self.rolled_number}, Win: {self.is_win}"
    
    def format_number(self):
        number = float(self.win_amount)
        if number.is_integer():
            return str(int(number))
        else:
            return str(number).rstrip('0').rstrip(',')