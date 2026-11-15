// "Call us" page: one big button. Press it -> backend creates a room with Amrutha -> we join with the mic.
import { useState } from 'react'
import { LiveKitRoom } from '@livekit/components-react'
import { apiPost } from '../../lib/api'
import CallScreen from '../../components/CallScreen'

const BUSINESS = 'Amrith Sagar Catering'

export default function CallUs() {
  const [call, setCall] = useState(null)      // {room, token, livekit_url} while in a call
  const [status, setStatus] = useState('idle') // idle | starting | in_call | ended
  const [error, setError] = useState('')

  async function startCall() {
    setError('')
    setStatus('starting')
    try {
      // ask for the mic first, so the browser's permission popup appears right away
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      stream.getTracks().forEach((t) => t.stop())
      setCall(await apiPost('/inbound/start'))
      setStatus('in_call')
    } catch (e) {
      setError(e.name === 'NotAllowedError' ? 'Please allow the microphone to talk to us.' : e.message)
      setStatus('idle')
    }
  }

  function endCall() {
    setCall(null)
    setStatus('ended')
  }

  if (status === 'in_call' && call) {
    return (
      <main className="phone">
        <LiveKitRoom serverUrl={call.livekit_url} token={call.token} connect audio video={false} onDisconnected={endCall}>
          <CallScreen businessName={BUSINESS} onHangUp={endCall} />
        </LiveKitRoom>
      </main>
    )
  }

  return (
    <main className="phone">
      <div className="call-card">
        <div className="avatar">A</div>
        <h2>{BUSINESS}</h2>
        {status === 'ended' ? (
          <p className="muted">Thank you for calling! You can call again any time.</p>
        ) : (
          <p className="muted">Talk to Amrutha, our AI assistant, in Kannada, English, Hindi, Tamil or Telugu.</p>
        )}
        <button className="btn btn-green btn-big" onClick={startCall} disabled={status === 'starting'}>
          {status === 'starting' ? 'Calling…' : status === 'ended' ? 'Call again' : 'Call us'}
        </button>
        {error && <p className="error">{error}</p>}
      </div>
    </main>
  )
}
