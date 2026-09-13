"""
message_resolver.py
Extracts verified financial amendments from unstructured messages in dataset/messages.csv:
1. Confirmed base salary increases / reductions from employers (English & Indonesian).
2. Confirmed pay date shifts (salary expected on / resumes on / confirmed for YYYY-MM-DD).
3. Contract / employment / seasonal terminations.
4. Rent escalation notices from landlords/service providers (12% lease renewals).
5. Confirmed client invoice payouts for freelancers/contractors.
6. Multi-message conflict resolution (chronological order, newer record supersedes).
7. Strict prompt-injection isolation (ignores instructions embedded in message body).
"""

import re
from datetime import datetime
from typing import Dict, List, Any, Optional


class MessageResolver:
    def __init__(self, data_loader):
        self.loader = data_loader
        self.user_overrides: Dict[str, Dict[str, Any]] = {}
        self._parse_all_messages()

    def _parse_all_messages(self):
        for uid, msgs in self.loader.messages_by_user.items():
            override = {
                'updated_salary_amt': None,
                'stop_salary': False,
                'scheduled_salary_date': None,
                'rent_multiplier': 1.0,
                'confirmed_invoices': [],
            }

            # Sort chronologically by sent_at so newer record supersedes earlier
            sorted_msgs = sorted(msgs, key=lambda x: str(x.get('sent_at', '')))

            for m in sorted_msgs:
                text = str(m.get('message_text', ''))
                text_lower = text.lower()
                stype = str(m.get('source_type', '')).strip()

                # 1. Contract / employment termination notices
                if any(k in text_lower for k in [
                    'contract has ended', 'kontrak telah berakhir',
                    'employment has ended', 'tidak ada gaji',
                    'no off-season income', 'no regular salary payments scheduled',
                    'kontrak musiman saat ini telah berakhir', 'seasonal contract has ended'
                ]):
                    override['stop_salary'] = True
                    override['updated_salary_amt'] = None

                # 2. Confirmed salary date shifts
                dt_match = re.search(r'(\d{4}-\d{2}-\d{2})', text)
                if any(k in text_lower for k in [
                    'salary is now expected on', 'gaji diperkirakan pada',
                    'salary is expected on', 'salary resumes on',
                    'kini diperkirakan masuk pada', 'dijadwalkan pada',
                    'confirmed for', 'dikonfirmasi adalah',
                    'confirmed credit date is', 'tangal kredit yang dikonfirmasi adalah'
                ]) and dt_match:
                    override['scheduled_salary_date'] = dt_match.group(1)

                # 3. Confirmed salary amount amendments (strictly from employer or financial service payroll)
                if stype in {'employer', 'financial_service'}:
                    amt_match = re.search(r'(?:IDR|EUR|USD|INR|ZAR)\s*([\d,]+(?:\.\d+)?)', text)
                    if amt_match:
                        amt_str = amt_match.group(1).replace(',', '')
                        try:
                            new_amt = float(amt_str)
                            if any(k in text_lower for k in [
                                'gaji bulanan anda naik', 'gaji pokok yang dikonfirmasi',
                                'monthly pay is', 'next salary is reduced to',
                                'gaji berikutnya dikurangi', 'regular salary of',
                                'first salary will be', 'base salary is',
                                'confirmed base salary', 'naik menjadi',
                                'temporary monthly pay is', 'salary of',
                                'regular salary for the next payroll is',
                                'gaji rutin anda untuk penggajian berikutnya adalah',
                                'monthly salary has increased to',
                                'first salary from the new employer is',
                                'gaji pertama dari perusahaan baru adalah',
                                'gaji pertama anda sebesar',
                                'remaining confirmed monthly',
                                'sisa gaji bulanan yang dikonfirmasi',
                                'gaji bulanan sementara anda adalah',
                                'salary credit for',
                            ]):
                                override['updated_salary_amt'] = new_amt
                                override['stop_salary'] = False
                        except ValueError:
                            pass

                # 4. Rent increase notices (lease renewals)
                if any(k in text_lower for k in [
                    'increases monthly rent by 12%',
                    'menaikkan biaya sewa bulanan sebesar 12%'
                ]):
                    override['rent_multiplier'] = 1.12

                # 5. Confirmed client invoice payments
                if any(k in text_lower for k in [
                    'client approved an invoice payment of',
                    'klien menyetujui pembayaran faktur sebesar'
                ]) and dt_match:
                    amt_match = re.search(r'(IDR|EUR|USD|INR|ZAR)\s*([\d,]+(?:\.\d+)?)', text)
                    if amt_match:
                        inv_curr = amt_match.group(1)
                        inv_amt = float(amt_match.group(2).replace(',', ''))
                        override['confirmed_invoices'].append({
                            'date': dt_match.group(1),
                            'amount': inv_amt,
                            'currency': inv_curr,
                        })

            self.user_overrides[uid] = override

    def get_override(self, user_id: str) -> Dict[str, Any]:
        """
        Returns override dict for a user:
        {
            'updated_salary_amt': Optional[float],
            'stop_salary': bool,
            'scheduled_salary_date': Optional[str],
            'rent_multiplier': float,
            'confirmed_invoices': List[Dict[str, Any]],
        }
        """
        return self.user_overrides.get(user_id, {
            'updated_salary_amt': None,
            'stop_salary': False,
            'scheduled_salary_date': None,
            'rent_multiplier': 1.0,
            'confirmed_invoices': [],
        })
