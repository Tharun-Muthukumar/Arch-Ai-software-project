import { useMutation } from '@tanstack/react-query'
import { CalendarDays, LoaderCircle, Mail, Phone, Save, User } from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
import { useAuth } from '../context/AuthContext'
import { updateProfile } from '../lib/api'
import { formatUpdatedAt, getErrorMessage } from '../lib/utils'

export function ProfilePage() {
  const { user, setUser } = useAuth()
  const [phoneNumber, setPhoneNumber] = useState(user?.phone_number ?? '')
  const mutation = useMutation({
    mutationFn: () => updateProfile(phoneNumber),
    onSuccess: (response) => setUser(response.user),
  })

  useEffect(() => {
    setPhoneNumber(user?.phone_number ?? '')
  }, [user?.phone_number])

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    mutation.mutate()
  }

  if (!user) {
    return null
  }

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <div>
        <span className="pill">Account</span>
        <h2 className="section-title mt-2">Profile</h2>
      </div>

      <section className="panel">
        <dl className="grid gap-5 sm:grid-cols-2">
          <div>
            <dt className="flex items-center gap-2 text-sm text-muted"><User className="h-4 w-4" /> Username</dt>
            <dd className="mt-1 font-medium">{user.username}</dd>
          </div>
          <div>
            <dt className="flex items-center gap-2 text-sm text-muted"><Mail className="h-4 w-4" /> Email</dt>
            <dd className="mt-1 break-all font-medium">{user.email}</dd>
          </div>
          <div>
            <dt className="flex items-center gap-2 text-sm text-muted"><Phone className="h-4 w-4" /> Phone</dt>
            <dd className="mt-1 font-medium">{user.phone_number}</dd>
          </div>
          <div>
            <dt className="flex items-center gap-2 text-sm text-muted"><CalendarDays className="h-4 w-4" /> Joined</dt>
            <dd className="mt-1 font-medium">{formatUpdatedAt(user.created_at)}</dd>
          </div>
        </dl>
      </section>

      <form className="panel" onSubmit={handleSubmit}>
        <h3 className="font-semibold">Update phone number</h3>
        <label className="mt-3 block max-w-md space-y-1">
          <span className="text-sm font-medium">Phone number</span>
          <input
            className="input-shell"
            type="tel"
            autoComplete="tel"
            required
            value={phoneNumber}
            onChange={(event) => setPhoneNumber(event.target.value)}
          />
        </label>
        {mutation.isError ? <p className="mt-2 text-sm text-red-300" role="alert">{getErrorMessage(mutation.error)}</p> : null}
        {mutation.isSuccess ? <p className="mt-2 text-sm text-green-300">Profile updated.</p> : null}
        <button className="button-brand mt-4 gap-2" type="submit" disabled={mutation.isPending}>
          {mutation.isPending ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
          Save
        </button>
      </form>
    </div>
  )
}
