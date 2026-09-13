"""
data_loader.py
Loads and indexes all dataset files into structured, fast-access in-memory objects.
"""

import os
import pandas as pd
from typing import Dict, List, Any, Tuple, Optional


class DataLoader:
    def __init__(self, dataset_dir: str = 'dataset'):
        self.dataset_dir = dataset_dir

        # DataFrames
        self.df_profiles = pd.read_csv(os.path.join(dataset_dir, 'financial_profiles.csv'))
        self.df_events = pd.read_csv(os.path.join(dataset_dir, 'financial_events.csv'))
        self.df_fx = pd.read_csv(os.path.join(dataset_dir, 'exchange_rates.csv'))
        self.df_requests = pd.read_csv(os.path.join(dataset_dir, 'requests.csv'))
        self.df_samples = pd.read_csv(os.path.join(dataset_dir, 'sample_requests.csv'))
        self.df_options = pd.read_csv(os.path.join(dataset_dir, 'request_payment_options.csv'))
        self.df_messages = pd.read_csv(os.path.join(dataset_dir, 'messages.csv'))
        self.df_images = pd.read_csv(os.path.join(dataset_dir, 'images.csv'))

        # Indexes
        self._build_indexes()

    def _build_indexes(self):
        # 1. Profiles by user_id
        self.profiles: Dict[str, Dict[str, Any]] = {}
        for _, row in self.df_profiles.iterrows():
            d = row.to_dict()
            # Clean payment methods
            if pd.notna(d.get('payment_methods_user_will_consider')):
                d['payment_methods'] = set(str(d['payment_methods_user_will_consider']).split('|'))
            else:
                d['payment_methods'] = set()

            # Clean willing to reduce / stop
            if pd.notna(d.get('expense_categories_user_is_willing_to_reduce')):
                d['categories_to_reduce'] = set(str(d['expense_categories_user_is_willing_to_reduce']).split('|'))
            else:
                d['categories_to_reduce'] = set()

            if pd.notna(d.get('expense_categories_user_is_willing_to_stop')):
                d['categories_to_stop'] = set(str(d['expense_categories_user_is_willing_to_stop']).split('|'))
            else:
                d['categories_to_stop'] = set()

            if pd.notna(d.get('protected_spending_categories')):
                d['protected_categories'] = set(str(d['protected_spending_categories']).split('|'))
            else:
                d['protected_categories'] = set()

            self.profiles[d['user_id']] = d

        # 2. Events by user_id
        self.events_by_user: Dict[str, List[Dict[str, Any]]] = {}
        self.events_by_id: Dict[str, Dict[str, Any]] = {}
        for _, row in self.df_events.iterrows():
            d = row.to_dict()
            uid = d['user_id']
            eid = d['event_id']
            if uid not in self.events_by_user:
                self.events_by_user[uid] = []
            self.events_by_user[uid].append(d)
            self.events_by_id[eid] = d

        # Sort each user's events by settlement_date
        for uid in self.events_by_user:
            self.events_by_user[uid].sort(key=lambda x: str(x['settlement_date']))

        # 3. Requests
        self.requests: List[Dict[str, Any]] = [row.to_dict() for _, row in self.df_requests.iterrows()]
        self.requests_by_id: Dict[str, Dict[str, Any]] = {r['request_id']: r for r in self.requests}

        # 4. Samples
        self.samples: List[Dict[str, Any]] = [row.to_dict() for _, row in self.df_samples.iterrows()]
        self.samples_by_id: Dict[str, Dict[str, Any]] = {r['request_id']: r for r in self.samples}

        # 5. Payment Options by request_id
        self.options_by_request: Dict[str, List[Dict[str, Any]]] = {}
        for _, row in self.df_options.iterrows():
            d = row.to_dict()
            rid = d['request_id']
            if rid not in self.options_by_request:
                self.options_by_request[rid] = []
            self.options_by_request[rid].append(d)

        # 6. Messages by user_id and by related_event_id
        self.messages_by_user: Dict[str, List[Dict[str, Any]]] = {}
        self.messages_by_event: Dict[str, List[Dict[str, Any]]] = {}
        for _, row in self.df_messages.iterrows():
            d = row.to_dict()
            uid = d['user_id']
            if uid not in self.messages_by_user:
                self.messages_by_user[uid] = []
            self.messages_by_user[uid].append(d)

            rev = d.get('related_event_id')
            if pd.notna(rev) and str(rev).strip():
                ev_id = str(rev).strip()
                if ev_id not in self.messages_by_event:
                    self.messages_by_event[ev_id] = []
                self.messages_by_event[ev_id].append(d)

        # 7. Images by request_id and by related_event_id
        self.images_by_request: Dict[str, List[Dict[str, Any]]] = {}
        self.images_by_event: Dict[str, Dict[str, Any]] = {}
        for _, row in self.df_images.iterrows():
            d = row.to_dict()
            rid = d['request_id']
            if rid not in self.images_by_request:
                self.images_by_request[rid] = []
            self.images_by_request[rid].append(d)

            rev = d.get('related_event_id')
            if pd.notna(rev) and str(rev).strip():
                self.images_by_event[str(rev).strip()] = d

        # 8. Exchange rates: lookup by (rate_date, from_currency, to_currency)
        self.fx_rates: Dict[Tuple[str, str, str], float] = {}
        # Also track latest rate for pair in case dates extend beyond published table
        self.latest_fx: Dict[Tuple[str, str], Tuple[str, float]] = {}
        for _, row in self.df_fx.iterrows():
            d = row.to_dict()
            date_str = str(d['rate_date']).strip()
            from_curr = str(d['from_currency']).strip()
            to_curr = str(d['to_currency']).strip()
            rate = float(d['rate'])

            self.fx_rates[(date_str, from_curr, to_curr)] = rate
            pair = (from_curr, to_curr)
            if pair not in self.latest_fx or date_str > self.latest_fx[pair][0]:
                self.latest_fx[pair] = (date_str, rate)

    def get_fx_rate(self, settlement_date: str, from_currency: str, to_currency: str) -> float:
        """
        Returns the exchange rate from from_currency to to_currency on settlement_date.
        If identical currencies, returns 1.0.
        Uses exact match on rate_date. If settlement_date is later than available rates,
        uses the latest published rate for that pair.
        """
        if from_currency == to_currency:
            return 1.0

        key = (settlement_date, from_currency, to_currency)
        if key in self.fx_rates:
            return self.fx_rates[key]

        # Check if latest rate exists for pair
        pair = (from_currency, to_currency)
        if pair in self.latest_fx:
            return self.latest_fx[pair][1]

        raise KeyError(f"No FX rate found for {from_currency} -> {to_currency} on {settlement_date}")
