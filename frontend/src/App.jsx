// Routes. Business and admin dashboards come in Milestone 8.
import { BrowserRouter, Link, Route, Routes } from 'react-router-dom'
import CallUs from './pages/customer/CallUs'
import IncomingCall from './pages/customer/IncomingCall'

function Home() {
  return (
    <main className="shell">
      <h1>Amrith Sagar Voice Agent</h1>
      <p>Customer pages:</p>
      <ul>
        <li><Link to="/call">Call us</Link> (inbound call to Amrutha)</li>
        <li>/c/&lt;token&gt;: a customer's personal page where outbound calls ring</li>
      </ul>
    </main>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/call" element={<CallUs />} />
        <Route path="/c/:token" element={<IncomingCall />} />
      </Routes>
    </BrowserRouter>
  )
}
