import type { WorkspaceCreatePayload } from '../types/api'

export const sampleProject: WorkspaceCreatePayload = {
  title: 'VoltReserve',
  description:
    'Build an EV charging station booking platform for fast-growing metro cities in India. The system should support station discovery, charger availability checks, slot reservations, secure payment, charging session tracking, cancellation and refund flows, driver history, operator controls, and admin analytics.',
  business_context:
    'The company wants a polished first release for city-wide pilots, then expansion across additional regions. Reliability, map accuracy, payment integrity, and clear operator tooling are all critical. The first release should be web-first, with mobile apps planned next.',
  budget: 'medium',
  preferred_cloud: 'AWS',
  team_size: 6,
  constraints: [
    'Must use PostgreSQL',
    'Must support SSO for admin users',
    'Audit logs required',
    'Real-time station availability required',
    '99.9% availability target',
  ],
}
