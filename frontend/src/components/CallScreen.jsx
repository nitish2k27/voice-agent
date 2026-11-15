// The in-call screen, shared by "Call us" and the incoming-call page.
// Must be used inside <LiveKitRoom>. Shows: who you're talking to, a timer, what the agent is doing,
// optional live captions, and Mute / Hang up buttons.
import { useEffect, useState } from 'react'
import {
  RoomAudioRenderer,
  StartAudio,
  useConnectionState,
  useLocalParticipant,
  useRoomContext,
  useVoiceAssistant,
} from '@livekit/components-react'

const AGENT_STATE_TEXT = {
  connecting: 'Connecting…',
  initializing: 'Connecting…',
  listening: 'Listening',
  thinking: 'Thinking…',
  speaking: 'Speaking',
}

function useTimer() {
  const [seconds, setSeconds] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setSeconds((s) => s + 1), 1000)
    return () => clearInterval(id)
  }, [])
  const mm = String(Math.floor(seconds / 60)).padStart(2, '0')
  const ss = String(seconds % 60).padStart(2, '0')
  return `${mm}:${ss}`
}

export default function CallScreen({ businessName, onHangUp }) {
  const room = useRoomContext()
  const connection = useConnectionState()
  const { state, agentTranscriptions } = useVoiceAssistant()
  const { localParticipant, isMicrophoneEnabled } = useLocalParticipant()
  const time = useTimer()
  const [showCaptions, setShowCaptions] = useState(false)

  const lastCaption = agentTranscriptions?.length ? agentTranscriptions[agentTranscriptions.length - 1].text : ''

  async function hangUp() {
    await room.disconnect()
    onHangUp()
  }

  return (
    <div className="call-card">
      <RoomAudioRenderer />
      {/* Some phones block audio until the user taps once: this shows a button only when needed */}
      <StartAudio label="Tap to hear the call" className="btn" />

      <div className="avatar">A</div>
      <h2>Amrutha</h2>
      <p className="muted">{businessName} · AI assistant</p>
      <p className="timer">{time}</p>
      <p className="agent-state">
        {connection !== 'connected' ? 'Connecting…' : AGENT_STATE_TEXT[state] || 'Waiting for Amrutha…'}
      </p>

      {showCaptions && <p className="caption">{lastCaption || '…'}</p>}

      <div className="call-buttons">
        <button className="btn" onClick={() => localParticipant.setMicrophoneEnabled(!isMicrophoneEnabled)}>
          {isMicrophoneEnabled ? 'Mute' : 'Unmute'}
        </button>
        <button className="btn" onClick={() => setShowCaptions((v) => !v)}>
          {showCaptions ? 'Hide captions' : 'Captions'}
        </button>
        <button className="btn btn-red" onClick={hangUp}>Hang up</button>
      </div>
    </div>
  )
}
