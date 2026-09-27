import { createContext } from "react"
import { demoDrafts, type DraftRepository } from "../api/drafts"
export const DraftContext = createContext<DraftRepository>(demoDrafts)
