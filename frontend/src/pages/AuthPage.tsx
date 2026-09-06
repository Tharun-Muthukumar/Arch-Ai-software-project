import { Eye, EyeOff, LoaderCircle, LogIn, UserPlus } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { signUp } from '../lib/api'
import { getErrorMessage } from '../lib/utils'

interface AuthPageProps {
  mode: 'sign-in' | 'sign-up'
}

interface AuthLocationState {
  from?: string
  message?: string
}

export function AuthPage({ mode }: AuthPageProps) {
  const isSignUp = mode === 'sign-up'
  const { user, login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const locationState = (location.state as AuthLocationState | null) ?? {}
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [values, setValues] = useState({
    username: '',
    email: '',
    phone_number: '',
    identifier: '',
    password: '',
    password_confirmation: '',
  })

  if (user) {
    return <Navigate to="/dashboard" replace />
  }

  function updateValue(field: keyof typeof values, value: string) {
    setValues((current) => ({ ...current, [field]: value }))
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setIsSubmitting(true)
    try {
      if (isSignUp) {
        await signUp({
          username: values.username,
          email: values.email,
          phone_number: values.phone_number,
          password: values.password,
          password_confirmation: values.password_confirmation,
        })
        navigate('/sign-in', {
          replace: true,
          state: { message: 'Account created. Sign in to continue.' },
        })
      } else {
        await login({ identifier: values.identifier, password: values.password })
        navigate(locationState.from || '/dashboard', { replace: true })
      }
    } catch (submitError) {
      setError(getErrorMessage(submitError, 'Authentication failed.'))
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center px-4 py-8">
      <section className="w-full max-w-md">
        <div className="mb-6 text-center">
          <h1 className="text-2xl font-bold" style={{ color: 'var(--brand)' }}>ArchAI</h1>
          <h2 className="mt-2 text-xl font-semibold">{isSignUp ? 'Create account' : 'Sign in'}</h2>
        </div>

        <form className="panel space-y-4" onSubmit={handleSubmit}>
          {locationState.message && !isSignUp ? (
            <div className="rounded-md border border-green-700 bg-green-950/40 px-3 py-2 text-sm text-green-300">
              {locationState.message}
            </div>
          ) : null}
          {error ? (
            <div className="rounded-md border border-red-800 bg-red-950/40 px-3 py-2 text-sm text-red-300" role="alert">
              {error}
            </div>
          ) : null}

          {isSignUp ? (
            <>
              <label className="block space-y-1">
                <span className="text-sm font-medium">Username</span>
                <input
                  className="input-shell"
                  autoComplete="username"
                  required
                  minLength={3}
                  maxLength={50}
                  value={values.username}
                  onChange={(event) => updateValue('username', event.target.value)}
                />
              </label>
              <label className="block space-y-1">
                <span className="text-sm font-medium">Email address</span>
                <input
                  className="input-shell"
                  type="email"
                  autoComplete="email"
                  required
                  value={values.email}
                  onChange={(event) => updateValue('email', event.target.value)}
                />
              </label>
              <label className="block space-y-1">
                <span className="text-sm font-medium">Phone number</span>
                <input
                  className="input-shell"
                  type="tel"
                  autoComplete="tel"
                  required
                  value={values.phone_number}
                  onChange={(event) => updateValue('phone_number', event.target.value)}
                />
              </label>
            </>
          ) : (
            <label className="block space-y-1">
              <span className="text-sm font-medium">Username or email</span>
              <input
                className="input-shell"
                autoComplete="username"
                required
                value={values.identifier}
                onChange={(event) => updateValue('identifier', event.target.value)}
              />
            </label>
          )}

          <label className="block space-y-1">
            <span className="text-sm font-medium">Password</span>
            <div className="relative">
              <input
                className="input-shell pr-11"
                type={showPassword ? 'text' : 'password'}
                autoComplete={isSignUp ? 'new-password' : 'current-password'}
                required
                minLength={isSignUp ? 8 : 1}
                value={values.password}
                onChange={(event) => updateValue('password', event.target.value)}
              />
              <button
                type="button"
                className="absolute right-1 top-1/2 -translate-y-1/2 p-2 text-slate-400 hover:text-white"
                onClick={() => setShowPassword((current) => !current)}
                title={showPassword ? 'Hide password' : 'Show password'}
                aria-label={showPassword ? 'Hide password' : 'Show password'}
              >
                {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
          </label>

          {isSignUp ? (
            <label className="block space-y-1">
              <span className="text-sm font-medium">Re-enter password</span>
              <input
                className="input-shell"
                type={showPassword ? 'text' : 'password'}
                autoComplete="new-password"
                required
                minLength={8}
                value={values.password_confirmation}
                onChange={(event) => updateValue('password_confirmation', event.target.value)}
              />
            </label>
          ) : null}

          <button type="submit" className="button-brand w-full gap-2" disabled={isSubmitting}>
            {isSubmitting ? (
              <LoaderCircle className="h-4 w-4 animate-spin" />
            ) : isSignUp ? (
              <UserPlus className="h-4 w-4" />
            ) : (
              <LogIn className="h-4 w-4" />
            )}
            {isSubmitting ? 'Please wait...' : isSignUp ? 'Create account' : 'Sign in'}
          </button>
        </form>

        <p className="mt-4 text-center text-sm text-muted">
          {isSignUp ? 'Already have an account?' : 'New to ArchAI?'}{' '}
          <Link className="font-medium text-amber-400 hover:text-amber-300" to={isSignUp ? '/sign-in' : '/sign-up'}>
            {isSignUp ? 'Sign in' : 'Create account'}
          </Link>
        </p>
      </section>
    </main>
  )
}
