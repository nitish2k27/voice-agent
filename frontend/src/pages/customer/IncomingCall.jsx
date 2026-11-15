// The customer's personal link /c/:token. It listens to the server (SSE) and rings when Amrutha calls.
//   idle -> "We'll call you here"   ringing -> Accept / Decline + countdown   missed -> "You missed our call"
import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { LiveKitRoom } from '@livekit/components-react'
import { API_URL, apiPost } from '../../lib/api'
import CallScreen from '../../components/CallScreen'

export default function IncomingCall() {
  const { token } = useParams()
  const [page, setPage] = useState({ state: 'loading' })  // latest state from the server
  const [call, setCall] = useState(null)                   // {room, token, livekit_url} after Accept
  const [ended, setEnded] = useState(false)
  const [error, setError] = useState('')

  // live updates from the server
  useEffect(() => {
    const source = new EventSource(`${API_URL}/customer/${token}/events`)
    const update = (e) => setPage(JSON.parse(e.data))
    for (const name of ['idle', 'ringing', 'missed', 'in_call']) source.addEventListener(name, update)
    source.onerror = () => setPage((p) => (p.state === 'loading' ? { state: 'bad_link' } : p))
    return () => source.close()
  }, [token])

  // ringtone while ringing (a simple beep pattern; no audio file needed)
  useEffect(() => {
    if (page.state !== 'ringing' || call) return
    const ctx = new AudioContext()
    const beep = setInterval(() => {
      const osc = ctx.createOscillator()
      osc.frequency.value = 440
      osc.connect(ctx.destination)
      osc.start()
      osc.stop(ctx.currentTime + 0.4)
    }, 1500)
    return () => { clearInterval(beep); ctx.close() }
  }, [page.state, call])

  async function accept() {
    setError('')
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      stream.getTracks().forEach((t) => t.stop())
      setCall(await apiPost(`/customer/${token}/join`))
    } catch (e) {
      setError(e.name === 'NotAllowedError' ? 'Please allow the microphone to answer.' : e.message)
    }
  }

  async function decline() {
    await apiPost(`/customer/${token}/decline`).catch(() => {})
  }

  const business = page.business_name || 'Amrith Sagar Catering'

  if (call && !ended) {
    return (
      <main className="phone">
        <LiveKitRoom serverUrl={call.livekit_url} token={call.token} connect audio video={false}
                     onDisconnected={() => setEnded(true)}>
          <CallScreen businessName={business} onHangUp={() => setEnded(true)} />
        </LiveKitRoom>
      </main>
    )
  }

  return (
    <main className="phone">
      <div className="call-card">
        <div className="avatar">A</div>
        <h2>{business}</h2>

        {page.state === 'loading' && <p className="muted">Connecting…</p>}
        {page.state === 'bad_link' && <p className="error">This link doesn't work. Please check it.</p>}
        {ended && <p className="muted">Call ended. Thank you!</p>}

        {!ended && page.state === 'idle' && (
          <p className="muted">Hi {page.customer_name || 'there'}! Keep this page open. Amrutha will call you here.</p>
        )}
        {!ended && page.state === 'missed' && (
          <p className="muted">You missed our call. We'll try again a little later. Keep this page open.</p>
        )}
        {!ended && page.state === 'in_call' && <p className="muted">This call is already in progress.</p>}

        {!ended && page.state === 'ringing' && (
          <>
            <p className="ringing">Incoming call…</p>
            <p className="muted">{page.seconds_left}s</p>
            <div className="call-buttons">
              <button className="btn btn-green btn-big" onClick={accept}>Accept</button>
              <button className="btn btn-red btn-big" onClick={decline}>Decline</button>
            </div>
          </>
        )}
        {error && <p className="error">{error}</p>}
      </div>
    </main>
  )
}
