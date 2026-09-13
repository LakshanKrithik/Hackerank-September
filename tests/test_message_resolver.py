"""
tests/test_message_resolver.py
Unit tests for message_resolver.py.
Tests:
1. Salary increase extraction (Indonesian & English).
2. Contract termination extraction (Indonesian & English).
3. Salary date shift extraction.
4. Rent increase extraction (12% lease renewals).
5. Confirmed client invoice payout extraction.
6. Multi-message conflict resolution (chronological ordering, newer message supersedes).
"""

import unittest
import sys
import os

sys.path.insert(0, os.path.abspath('code'))
from message_resolver import MessageResolver


class MockLoader:
    def __init__(self, msgs_by_user):
        self.messages_by_user = msgs_by_user


class TestMessageResolver(unittest.TestCase):

    def test_salary_increase_extraction(self):
        msgs = {
            'u2': [
                {
                    'source_type': 'employer',
                    'sent_at': '2025-07-29T09:30:00Z',
                    'message_text': 'Rincian penggajian Anda di Cobalt Systems telah berubah. Gaji bulanan Anda naik menjadi IDR 42750000. Perubahan ini berlaku mulai 2025-08-15.'
                }
            ],
            'u36': [
                {
                    'source_type': 'employer',
                    'sent_at': '2026-07-01T09:30:00Z',
                    'message_text': 'Hi, Northstar Labs payroll here. Your monthly salary has increased to USD 2988. The change applies from 2026-07-15.'
                }
            ]
        }
        res = MessageResolver(MockLoader(msgs))
        ov2 = res.get_override('u2')
        self.assertEqual(ov2['updated_salary_amt'], 42750000.0)
        self.assertFalse(ov2['stop_salary'])

        ov36 = res.get_override('u36')
        self.assertEqual(ov36['updated_salary_amt'], 2988.0)

    def test_contract_termination_extraction(self):
        msgs = {
            'u12': [
                {
                    'source_type': 'employer',
                    'sent_at': '2026-03-25T09:30:00Z',
                    'message_text': 'The current seasonal contract has ended. No off-season income or renewal has been confirmed.'
                }
            ],
            'u201': [
                {
                    'source_type': 'employer',
                    'sent_at': '2026-03-26T09:30:00Z',
                    'message_text': 'Tim payroll Northstar Labs telah mengirim pembaruan. Kontrak musiman saat ini telah berakhir. Belum ada pendapatan di luar musim.'
                }
            ]
        }
        res = MessageResolver(MockLoader(msgs))
        ov12 = res.get_override('u12')
        self.assertTrue(ov12['stop_salary'])
        self.assertIsNone(ov12['updated_salary_amt'])

        ov201 = res.get_override('u201')
        self.assertTrue(ov201['stop_salary'])

    def test_salary_date_shift_extraction(self):
        msgs = {
            'u7': [
                {
                    'source_type': 'employer',
                    'sent_at': '2024-08-20T09:30:00Z',
                    'message_text': 'BrightPath Media has updated your payroll record. Your confirmed salary is now expected on 2024-09-23.'
                }
            ]
        }
        res = MessageResolver(MockLoader(msgs))
        ov = res.get_override('u7')
        self.assertEqual(ov['scheduled_salary_date'], '2024-09-23')

    def test_rent_increase_extraction(self):
        msgs = {
            'u16': [
                {
                    'source_type': 'service_provider',
                    'sent_at': '2024-08-15T09:30:00Z',
                    'message_text': 'StayLedger wanted to let you know about a change on your account. The renewed lease increases monthly rent by 12%.'
                }
            ]
        }
        res = MessageResolver(MockLoader(msgs))
        ov = res.get_override('u16')
        self.assertEqual(ov['rent_multiplier'], 1.12)

    def test_confirmed_invoice_extraction(self):
        msgs = {
            'u34': [
                {
                    'source_type': 'service_provider',
                    'sent_at': '2024-11-23T09:30:00Z',
                    'message_text': 'Hi, InvoiceLane here. The client approved an invoice payment of INR 196000. Settlement is expected on 2024-12-15.'
                }
            ]
        }
        res = MessageResolver(MockLoader(msgs))
        ov = res.get_override('u34')
        self.assertEqual(len(ov['confirmed_invoices']), 1)
        self.assertEqual(ov['confirmed_invoices'][0]['amount'], 196000.0)
        self.assertEqual(ov['confirmed_invoices'][0]['date'], '2024-12-15')
        self.assertEqual(ov['confirmed_invoices'][0]['currency'], 'INR')

    def test_multi_message_conflict_resolution(self):
        # Earlier message announces salary raise, later message announces contract termination
        msgs = {
            'u_multi': [
                {
                    'source_type': 'employer',
                    'sent_at': '2025-01-10T09:30:00Z',
                    'message_text': 'Your monthly salary has increased to EUR 2500.'
                },
                {
                    'source_type': 'employer',
                    'sent_at': '2025-02-15T09:30:00Z',
                    'message_text': 'Your employment has ended. No further regular salary payments scheduled.'
                }
            ]
        }
        res = MessageResolver(MockLoader(msgs))
        ov = res.get_override('u_multi')
        # Later message should win: stop_salary = True, updated_salary_amt = None
        self.assertTrue(ov['stop_salary'])
        self.assertIsNone(ov['updated_salary_amt'])


if __name__ == '__main__':
    unittest.main()
